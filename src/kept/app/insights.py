"""The Insights page: calling hours, financial stress and overdue balances by place, and the uplift model's
surface, each aggregated in SQL so no single customer leaves this module.

Every area or point is a group of MIN_GROUP or more customers or cases (the cohort rule); smaller groups are
left out or come back as None. Postal geography (FSA, its centroid) is a proxy attribute: it is read here for
display and monitoring only, never as a model input, tier or rule.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import date
from typing import Any, Literal, TypeVar

import duckdb
import numpy as np
import pandas as pd
from pydantic import BaseModel

MIN_GROUP = 50
T = TypeVar("T")


# ------------------------------------------------------------------ calling hours (#103)
class ProvinceHours(BaseModel):
    province: str
    time_zone: str  # IANA, the most common on the golden records in the province
    start: str  # "07:00", local, the customers' own permitted window (permission_gate's rule)
    end: str
    sunday_share: float  # customers who allow Sunday contact
    customers: int


class OutOfHours(BaseModel):
    province: str
    day: str  # Mon..Sun, local
    hour: int  # local hour of the contact
    contacts: int


class CallingHours(BaseModel):
    provinces: list[ProvinceHours]
    bank: list[OutOfHours]  # the bank's contacts outside the customer's permitted hours
    bank_contacts: int
    bank_cases: int  # cases with at least one
    cases: int
    kept_cards: int  # tonight's cards with a contact action
    kept_outside: int  # of those, cards whose calling-hours check failed: the gate makes this 0


SQL_HOURS = """
select province_code, mode(time_zone), mode(permitted_call_start_local), mode(permitted_call_end_local),
       avg(coalesce(sunday_contact_permitted, false)::int), count(*)
from gold.c360_customer
where province_code is not null and time_zone is not null and permitted_call_start_local is not null
group by 1 having count(*) >= ? order by 1
"""
SQL_BANK_OUT_OF_HOURS = """
select c.province_code, h.day_of_week, h.contact_hour_local, count(*)
from silver.contact_history h join silver.collections_cases c using (case_id)
where not h.within_permitted_hours_flag and c.province_code is not null
group by all order by all
"""
SQL_KEPT_OUT_OF_HOURS = """
select count(*), count(*) filter (where exists (
    select 1 from (select unnest(from_json(json_extract(card, '$.checks'), '[{"check":"VARCHAR","passed":"BOOLEAN"}]')) as c)
    where c.check = 'calling_hours' and not c.passed))
from nba.cards where action is not null and action <> 'wait'
"""


def calling_hours(conn: duckdb.DuckDBPyConnection) -> CallingHours:
    with conn.cursor() as cur:
        provinces = [
            ProvinceHours(
                province=p, time_zone=tz, start=f"{s:%H:%M}", end=f"{e:%H:%M}", sunday_share=float(sun), customers=n
            )
            for p, tz, s, e, sun, n in cur.execute(SQL_HOURS, [MIN_GROUP]).fetchall()
        ]
        shown = {p.province for p in provinces}
        bank = [
            OutOfHours(province=p, day=d, hour=h, contacts=n)
            for p, d, h, n in cur.execute(SQL_BANK_OUT_OF_HOURS).fetchall()
            if p in shown
        ]
        contacts, cases = cur.execute(
            "select count(*), count(distinct case_id) from silver.contact_history where not within_permitted_hours_flag"
        ).fetchone() or (0, 0)
        (all_cases,) = cur.execute("select count(*) from silver.collections_cases").fetchone() or (0,)
        kept, outside = cur.execute(SQL_KEPT_OUT_OF_HOURS).fetchone() or (0, 0)
    return CallingHours(
        provinces=provinces,
        bank=bank,
        bank_contacts=contacts,
        bank_cases=cases,
        cases=all_cases,
        kept_cards=kept,
        kept_outside=outside,
    )


# ------------------------------------------------------------------ stress map (#112)
class StressCell(BaseModel):
    province: str
    month: date
    customers: int
    falling_cash_flow: float | None  # net cash flow lower than the month before; None under MIN_GROUP
    cash_flow_base: int
    payroll_delay: float | None  # employer pay more than 5 days late; None under MIN_GROUP
    payroll_base: int
    hardship: float | None  # a hardship-flagged collections case open at the month-end


class StressMap(BaseModel):
    months: list[date]
    cells: list[StressCell]


# Today's portfolio customers (features.account_points), at each of the last 12 month-ends.
SQL_STRESS = """
with pop as (
    select distinct p.golden_customer_id, g.province_code
    from features.account_points p join gold.c360_customer g using (golden_customer_id)
    where g.province_code is not null
),
months as (
    select distinct point_date as m from features.account_points where month_end order by m desc limit 12
),
cf as (  -- total net cash flow per customer and month-end, and the month-end before
    select golden_customer_id, point_date as m, sum(net_cash_flow) as v
    from features.account_points
    where month_end and kind = 'deposit' and net_cash_flow is not null
    group by all
),
falling as (
    select golden_customer_id, m,
           v < lag(v) over w and lag(m) over w = last_day(m - interval 1 month) as falling
    from cf window w as (partition by golden_customer_id order by m)
),
pay as (  -- employer pay: first credit of the month vs the last one before it plus the usual gap
    select x.golden_customer_id, last_day(cast(s.credit_month || '-01' as date)) as m,
           s.first_credit_date - lag(s.last_credit_date) over w
             - 30.4 / avg(s.credit_count) over (partition by s.deposit_account_id order by s.credit_month
                                                 rows between 3 preceding and 1 preceding) > 5 as late
    from silver.salary_credit_history s
    join silver.deposit_accounts a on a.deposit_account_id = s.deposit_account_id
    join gold.identity_crosswalk x
        on x.source_system = 'deposit' and x.source_key = a.src_customer_ref and x.valid_to is null
    where s.employer_flag = 'Y' and s.credit_count > 0
      and x.golden_customer_id in (select golden_customer_id from pop)
    window w as (partition by s.deposit_account_id order by s.credit_month)
),
pay_m as (select golden_customer_id, m, bool_or(late) as late from pay where late is not null group by all),
hard_m as (
    select distinct x.golden_customer_id, mo.m
    from silver.collections_cases c
    join gold.identity_crosswalk x
        on x.source_system = 'collections' and x.source_key = c.coll_customer_ref and x.valid_to is null
    join months mo on c.case_open_date <= mo.m and (c.outcome_date is null or c.outcome_date > mo.m)
    where c.hardship_flag
)
select p.province_code, mo.m, count(*),
       count(f.falling), avg(f.falling::int),
       count(y.late), avg(y.late::int),
       avg((h.golden_customer_id is not null)::int)
from pop p cross join months mo
left join falling f on f.golden_customer_id = p.golden_customer_id and f.m = mo.m
left join pay_m y on y.golden_customer_id = p.golden_customer_id and y.m = mo.m
left join hard_m h on h.golden_customer_id = p.golden_customer_id and h.m = mo.m
group by all order by all
"""


def stress_map(conn: duckdb.DuckDBPyConnection) -> StressMap:
    def share(base: int, v: float | None) -> float | None:
        return float(v) if base >= MIN_GROUP and v is not None else None

    with conn.cursor() as cur:
        rows = cur.execute(SQL_STRESS).fetchall()
    cells = [
        StressCell(
            province=p,
            month=m,
            customers=n,
            falling_cash_flow=share(nf, f),
            cash_flow_base=nf,
            payroll_delay=share(ny, y),
            payroll_base=ny,
            hardship=share(n, h),
        )
        for p, m, n, nf, f, ny, y, h in rows
        if n >= MIN_GROUP
    ]
    return StressMap(months=sorted({c.month for c in cells}), cells=cells)


# ------------------------------------------------------------------ 3D collections map (#102)
class FsaTower(BaseModel):
    fsa: str
    province: str | None
    city: str | None
    lat: float  # the FSA's centroid, not a customer's address
    lon: float
    cases: int
    overdue: float
    roll_rate: float | None  # cases 30+ days later by day 30 of the case, last 12 months; None under MIN_GROUP
    roll_base: int
    hardship: float
    green: int
    amber: int
    red: int
    none: int


class CollectionsMap(BaseModel):
    towers: list[FsaTower]
    hidden_fsas: int  # FSAs with fewer than MIN_GROUP of tonight's cases: left off the map
    hidden_cases: int


SQL_MAP = """
with fsa as (
    select x.golden_customer_id, any_value(c.fsa) as fsa
    from gold.identity_crosswalk x
    join silver.customers c on x.source_system = 'crm' and x.source_key = c.crm_customer_id and x.valid_to is null
    where c.fsa is not null
    group by 1
),
cards as (
    select f.fsa, count(*) as n, sum(n.total_overdue) as overdue, avg(coalesce(n.hardship, false)::int) as hardship,
           count(*) filter (where n.tier = 'green') as green, count(*) filter (where n.tier = 'amber') as amber,
           count(*) filter (where n.tier = 'red') as red, count(*) filter (where n.tier is null) as none
    from nba.cards n join fsa f using (golden_customer_id)
    group by 1
),
latest as (select max(case_open_date) as d from silver.collections_cases),
roll as (
    select f.fsa, count(*) as n, avg((c.dpd_at_day_30 >= c.entry_dpd + 30)::int) as r
    from silver.collections_cases c
    join gold.identity_crosswalk x
        on x.source_system = 'collections' and x.source_key = c.coll_customer_ref and x.valid_to is null
    join fsa f using (golden_customer_id)
    cross join latest l
    where c.dpd_at_day_30 is not null
      and c.case_open_date > l.d - interval 12 month and c.case_open_date <= l.d - interval 30 day
    group by 1
)
select k.fsa, g.province_code, g.city, g.centroid_lat, g.centroid_lon, k.n, k.overdue, k.hardship,
       k.green, k.amber, k.red, k.none, coalesce(r.n, 0), r.r
from cards k
join silver.geo_reference g using (fsa)
left join roll r using (fsa)
order by k.fsa
"""


def collections_map(conn: duckdb.DuckDBPyConnection) -> CollectionsMap:
    with conn.cursor() as cur:
        rows = cur.execute(SQL_MAP).fetchall()
    towers, hidden, hidden_cases = [], 0, 0
    for fsa, prov, city, lat, lon, n, overdue, hard, green, amber, red, none, rn, rr in rows:
        if n < MIN_GROUP:
            hidden, hidden_cases = hidden + 1, hidden_cases + n
            continue
        towers.append(
            FsaTower(
                fsa=fsa,
                province=prov,
                city=city,
                lat=float(lat),
                lon=float(lon),
                cases=n,
                overdue=float(overdue or 0),
                roll_rate=float(rr) if rn >= MIN_GROUP and rr is not None else None,
                roll_base=rn,
                hardship=float(hard or 0),
                green=green,
                amber=amber,
                red=red,
                none=none,
            )
        )
    return CollectionsMap(towers=towers, hidden_fsas=hidden, hidden_cases=hidden_cases)


# ------------------------------------------------------------------ uplift landscape (#109)
class UpliftGroup(BaseModel):
    action: str  # the card's action, "none" for no action
    cases: int
    dpd: float  # the group's mean days past due
    answer_rate: float
    uplift: float  # mean predicted call uplift (call minus wait)


class UpliftLandscape(BaseModel):
    model_version: str
    dpd: list[int]
    answer_rate: list[float]
    uplift: list[list[float]]  # [answer_rate][dpd]: P(paid in 14 days | call) - P(... | wait)
    held: dict[str, float | str | None]  # every other model input, at tonight's median (mode for categories)
    groups: list[UpliftGroup]  # tonight's cases by action, days past due and answer rate, MIN_GROUP or more
    cases: int  # tonight's cases with an answer rate (the rest have never been called)


GRID_DPD = list(range(0, 181, 6))
GRID_ANSWER = [round(i / 20, 2) for i in range(21)]
DPD_BIN, ANSWER_BIN = 30, 0.25


def held_inputs(frame: pd.DataFrame) -> dict[str, Any]:
    """Median of each numeric input, the most common value of the rest (None when all are missing)."""
    out: dict[str, Any] = {}
    for c in frame.columns:
        col = frame[c].dropna()
        if col.empty:
            out[c] = None
        elif pd.api.types.is_numeric_dtype(col) and not pd.api.types.is_bool_dtype(col):
            out[c] = float(col.astype(float).median())
        else:
            v = col.mode().iloc[0]
            out[c] = v.item() if hasattr(v, "item") else v
    return out


def uplift_landscape(conn: duckdb.DuckDBPyConnection, model: Any) -> UpliftLandscape:
    """The live uplift model scored on a days-past-due x answer-rate grid, other inputs held at tonight's
    medians; and tonight's cases, scored on their own inputs, grouped (MIN_GROUP or more) by card action."""
    cols: list[str] = list(model._columns)  # what the model was trained on, in its order
    with conn.cursor() as cur:
        frame = cur.execute(
            f"select coalesce(n.action, 'none') as card_action, {', '.join('f.' + c for c in cols)}"
            " from nba.cards n join features.case_features f"
            " on f.case_id = n.case_id and f.as_of = (select max(as_of) from features.case_features)"
        ).df()
    actions, X = frame.pop("card_action"), frame
    held = held_inputs(X)
    grid = pd.DataFrame(
        [{**held, "max_dpd": d, "answer_rate": a} for a in GRID_ANSWER for d in GRID_DPD], columns=cols
    )
    surface = model.uplift(grid)["call"].to_numpy().reshape(len(GRID_ANSWER), len(GRID_DPD))
    seen = (X["answer_rate"].notna() & X["max_dpd"].notna()).to_numpy()
    tonight = pd.DataFrame(
        {
            "action": actions[seen].to_numpy(),
            "dpd": X.loc[seen, "max_dpd"].astype(float).to_numpy(),
            "answer_rate": X.loc[seen, "answer_rate"].astype(float).to_numpy(),
            "uplift": model.uplift(X[seen])["call"].to_numpy() if seen.any() else np.array([]),
        }
    )
    tonight["dpd_bin"] = (tonight["dpd"].clip(0, GRID_DPD[-1]) // DPD_BIN).astype(int)
    tonight["answer_bin"] = (tonight["answer_rate"].clip(0, 0.999) // ANSWER_BIN).astype(int)
    g = tonight.groupby(["action", "dpd_bin", "answer_bin"]).agg(
        cases=("uplift", "size"), dpd=("dpd", "mean"), answer_rate=("answer_rate", "mean"), uplift=("uplift", "mean")
    )
    groups = [
        UpliftGroup(action=a, cases=int(r.cases), dpd=r.dpd, answer_rate=r.answer_rate, uplift=r.uplift)
        for (a, _, _), r in g[g["cases"] >= MIN_GROUP].iterrows()
    ]
    return UpliftLandscape(
        model_version=model.model_version,
        dpd=GRID_DPD,
        answer_rate=GRID_ANSWER,
        uplift=np.round(surface, 5).tolist(),
        held={k: v for k, v in held.items() if k not in ("max_dpd", "answer_rate")},
        groups=groups,
        cases=int(seen.sum()),
    )


# ------------------------------------------------------------------ the service
Name = Literal["calling_hours", "stress", "map", "uplift"]


class Insights:
    """The four views, computed on first use and kept until kept score writes new cards."""

    def __init__(self, conn: duckdb.DuckDBPyConnection, model: Any | None = None) -> None:
        self._conn, self._model = conn, model
        self._cache: dict[tuple[str, str], BaseModel] = {}
        self._lock = threading.Lock()

    def _get(self, name: Name, make: Callable[[], T]) -> T:
        with self._conn.cursor() as cur:
            (stamp,) = cur.execute("select max(scored_at)::varchar from nba.cards").fetchone() or (None,)
        key = (name, str(stamp))
        with self._lock:  # ponytail: one lock for all four; the first call of each takes a few seconds
            if key not in self._cache:
                self._cache = {k: v for k, v in self._cache.items() if k[1] == key[1]}
                self._cache[key] = make()  # type: ignore[assignment]
            return self._cache[key]  # type: ignore[return-value]

    def calling_hours(self) -> CallingHours:
        return self._get("calling_hours", lambda: calling_hours(self._conn))

    def stress(self) -> StressMap:
        return self._get("stress", lambda: stress_map(self._conn))

    def map(self) -> CollectionsMap:
        return self._get("map", lambda: collections_map(self._conn))

    def uplift(self) -> UpliftLandscape:
        if self._model is None:
            raise LookupError("no uplift model on this machine")
        return self._get("uplift", lambda: uplift_landscape(self._conn, self._model))
