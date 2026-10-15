"""The portfolio page: tonight's cards and the bank's own randomised test, summarised from the warehouse.

Every number on the page comes from one of the queries below, and each insight carries the SQL behind it, so a
reader can rerun it. Nothing is estimated here: the model's work is on the cards (nba.cards, from kept score).
"""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any, Literal

import duckdb
from pydantic import BaseModel

from kept.config import OPERATING_TZ

Sort = Literal["expected_value", "total_overdue", "max_dpd", "p_paid_14d"]
SORTS: tuple[Sort, ...] = ("expected_value", "total_overdue", "max_dpd", "p_paid_14d")


class Slice(BaseModel):
    key: str
    cases: int
    balance: float
    expected: float


class Cell(BaseModel):
    """One arm of the bank's randomised test: promise-kept rate and cure rate with Wilson 95% intervals."""

    test_cell: str
    cases: int
    promises: int
    kept_rate: float
    kept_lo: float
    kept_hi: float
    cure_rate: float
    cure_lo: float
    cure_hi: float


class CohortCell(BaseModel):
    quarter: str
    product: str
    promises: int
    kept_rate: float | None  # None under MIN_PROMISES: too few to show


class Insight(BaseModel):
    id: str
    title: str
    body: str
    tone: Literal["good", "warn", "info"]
    sql: str


class FlowLink(BaseModel):
    """One band of a Sankey: cases, and their money, from one node to the next."""

    source: str
    target: str
    cases: float
    amount: float


class Portfolio(BaseModel):
    as_of: datetime | None
    cases: int
    balance: float
    expected: float
    actionable: int
    red: int
    hardship: int
    hard_stops: int
    by_tier: list[Slice]
    by_action: list[Slice]
    by_bucket: list[Slice]
    ab_test: list[Cell]
    cohorts: list[CohortCell]
    insights: list[Insight]
    flow: list[FlowLink] = []  # tonight's run, gate by gate (_flow)


class MoneyFlow(BaseModel):
    """A year of cases entering at 1-30 days past due (scripts/business_case.py), as bands of their overdue at
    entry: today, and with Kept's base case. Cases are at the year's average overdue per case."""

    cases: int
    overdue: float
    written_off: float  # charged-off balance a year: rolled cases x charge-off rate x average charge-off
    written_off_kept: float
    gain: float  # base case: promised money paid more a year (promises dated to payday)
    today: list[FlowLink]
    with_kept: list[FlowLink]


class CaseRow(BaseModel):
    case_id: str
    display_name: str | None
    current_bucket: str | None
    max_dpd: int
    total_overdue: float
    action: str | None
    tier: str | None
    p_paid_14d: float | None
    expected_value: float
    hardship: bool
    hard_stop: bool


class CasePage(BaseModel):
    rows: list[CaseRow]
    total: int


class WorkloadCell(BaseModel):
    weekday: int  # 0 = Monday
    hour: int  # local hour in the operating time zone
    calls: int  # proposed calls whose window starts in this hour
    capacity: float  # agents' outbound attempts available in this hour


class Workload(BaseModel):
    """#115: tonight's proposed calls by weekday and hour against the call team's capacity."""

    time_zone: str
    calls: int
    capacity_from: date | None  # the capacity week used (the latest seven days of channel_capacity)
    capacity_to: date | None
    cells: list[WorkloadCell]


MIN_PROMISES = 30
Z = 1.96

SQL_SLICES = (
    "select coalesce({col}, 'none') as key, count(*), sum(total_overdue), sum(expected_value)"
    " from nba.cards group by 1 order by 3 desc"
)
SQL_AB = (
    "select test_cell, count(*), sum(promises_kept), sum(promises_kept + promises_broken),"
    " sum(cure_flag::int)"
    " from silver.collections_cases where coalesce(outcome, '') <> '' and test_cell is not null"
    " group by 1 order by 1"
)
SQL_COHORT = (
    "select strftime(date_trunc('quarter', case_open_date), '%Y-Q') || quarter(case_open_date) as q,"
    " primary_product, sum(promises_kept), sum(promises_kept + promises_broken)"
    " from silver.collections_cases where case_open_date >= (select max(case_open_date) from"
    " silver.collections_cases) - interval 2 year group by 1, 2 order by 1, 2"
)

SQL_FLOW = (
    "select hard_stop, hardship, tier, no_action_reason, json_extract(card, '$.hard_stop.fired')::varchar[],"
    " count(*), sum(total_overdue) from nba.cards group by all"
)
STOPS = ("deceased", "bankruptcy", "insolvency", "cease")  # strongest first: a case shows under one stop
SQL_CURED = (  # cases that don't roll (business_case.py's roll query): cured, or still 1-30 dpd at day 30
    "select count(*) filter (where dpd_at_day_30 = 0), count(*) filter (where dpd_at_day_30 between 1 and 30)"
    " from silver.collections_cases where entry_dpd between 1 and 30"
)


def wilson(k: int, n: int) -> tuple[float, float, float]:
    """Rate and Wilson 95% interval (0, 0, 0 when n is 0)."""
    if n == 0:
        return 0.0, 0.0, 0.0
    p = k / n
    d = 1 + Z * Z / n
    c = (p + Z * Z / (2 * n)) / d
    h = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / d
    return p, max(0.0, c - h), min(1.0, c + h)


def _slices(cur: duckdb.DuckDBPyConnection, col: str) -> list[Slice]:
    rows = cur.execute(SQL_SLICES.format(col=col)).fetchall()
    return [Slice(key=str(k), cases=n, balance=float(b or 0), expected=float(e or 0)) for k, n, b, e in rows]


def _no_action(reason: str | None) -> str:
    r = reason or ""  # the engine's own wording (kept.nba.engine)
    if r.startswith("Best action is to wait"):
        return "wait"
    return "holdout" if r.startswith("No action: old strategy") else "no_action"


def _flow(cur: duckdb.DuckDBPyConnection) -> list[FlowLink]:
    """Tonight's run as Sankey bands: open cases, the hard-stop gate (each stopped case under its strongest
    stop), the hardship screen, then the card: a tier or why there is no action."""
    bands: dict[tuple[str, str], list[float]] = {}

    def add(s: str, t: str, n: int, b: float) -> None:
        x = bands.setdefault((s, t), [0, 0.0])
        x[0] += n
        x[1] += b

    for stop, hardship, tier, reason, fired, n, bal in cur.execute(SQL_FLOW).fetchall():
        b = float(bal or 0)
        if stop:
            add("open", "hard_stop", n, b)
            add("hard_stop", next((s for s in STOPS if s in (fired or ())), "other_stop"), n, b)
            continue
        screen = "hardship" if hardship else "no_hardship"
        add("open", "contactable", n, b)
        add("contactable", screen, n, b)
        add(screen, tier or _no_action(reason), n, b)
    return [FlowLink(source=s, target=t, cases=n, amount=b) for (s, t), (n, b) in bands.items()]


def money_flow(conn: duckdb.DuckDBPyConnection, business: dict[str, Any]) -> MoneyFlow:
    """The business case's roll funnel (business_data.json) as overdue bands; the warehouse splits the cases
    that don't roll into cured and partly paid. With Kept: the base case's payday gain moves from rolled to
    paid, and its roll-rate cut (none in the base case) lowers the roll rate and the charge-offs with it."""
    r, base = business["roll"], business["scenarios"]["Base"]
    n, overdue, rate, co = r["inflow_cases"], r["inflow_overdue"], r["rate"], r["chargeoff_if_rolled"]
    per_case = overdue / n
    cur = conn.cursor()
    try:
        cured, partly = cur.execute(SQL_CURED).fetchone() or (0, 0)
    finally:
        cur.close()
    share = cured / (cured + partly) if cured + partly else 1.0
    gain = float(base["Promises dated to payday"])
    pts = (
        base["Roll-rate cut: charge-offs avoided"] / base["_rolled_per_pt"] if base["_rolled_per_pt"] else 0.0
    )

    def link(s: str, t: str, amount: float) -> FlowLink:
        return FlowLink(source=s, target=t, cases=amount / per_case, amount=amount)

    def bands(rate: float, moved: float) -> list[FlowLink]:
        rolled = overdue * rate - moved
        off = overdue * rate * co
        paid = overdue - rolled
        return [
            link("entered", "cured", paid * share),
            link("entered", "partly_paid", paid * (1 - share)),
            link("entered", "rolled", rolled),
            link("rolled", "charged_off", off),
            link("rolled", "not_charged_off", rolled - off),
        ]

    kept_rate = rate - pts / 100
    return MoneyFlow(
        cases=n,
        overdue=overdue,
        written_off=n * rate * co * r["avg_chargeoff"],
        written_off_kept=n * kept_rate * co * r["avg_chargeoff"],
        gain=gain,
        today=bands(rate, 0.0),
        with_kept=bands(kept_rate, gain),
    )


def _insights(p: Portfolio) -> list[Insight]:
    out: list[Insight] = []
    champ = next((c for c in p.ab_test if c.test_cell == "champion"), None)
    others = [c for c in p.ab_test if c.test_cell != "champion" and c.promises]
    if champ and others:
        overlap = all(c.kept_lo <= champ.kept_hi and champ.kept_lo <= c.kept_hi for c in others)
        rates = ", ".join(f"{c.test_cell} {c.kept_rate:.1%}" for c in others)
        out.append(
            Insight(
                id="ab",
                title="Contact strategies keep promises at the same rate"
                if overlap
                else "One strategy keeps promises at a different rate",
                body=f"Champion {champ.kept_rate:.1%} of {champ.promises:,} promises kept; {rates}. "
                + (
                    "Every 95% interval overlaps the champion's: channel and contact intensity do not"
                    " change the rate."
                    if overlap
                    else "At least one interval does not overlap the champion's."
                ),
                tone="info",
                sql=SQL_AB,
            )
        )
    red = next((s for s in p.by_tier if s.key == "red"), None)
    if red and p.balance:
        out.append(
            Insight(
                id="red",
                title=f"{red.balance / p.balance:.0%} of the balance at risk requires specialist review",
                body=f"{red.cases:,} Red cases hold ${red.balance:,.0f}. Each involves hardship or"
                " vulnerability and requires a hardship specialist and a second approver before any contact.",
                tone="warn",
                sql=SQL_SLICES.format(col="tier"),
            )
        )
    top = max(p.by_bucket, key=lambda s: s.expected, default=None)
    if top and p.expected:
        out.append(
            Insight(
                id="bucket",
                title=f"The largest share of expected recovery is in the {top.key} bucket",
                body=f"${top.expected:,.0f} of ${p.expected:,.0f} ({top.expected / p.expected:.0%}) across "
                f"{top.cases:,} cases. Expected recovery is the uplift over no contact"
                " multiplied by the balance.",
                tone="good",
                sql=SQL_SLICES.format(col="current_bucket"),
            )
        )
    if p.hard_stops:
        out.append(
            Insight(
                id="stops",
                title=f"{p.hard_stops:,} cases are excluded from contact",
                body="Cease requests, insolvency holds and deceased flags block contact"
                " before any model runs.",
                tone="info",
                sql="select count(*) from nba.cards where hard_stop",
            )
        )
    return out


def overview(conn: duckdb.DuckDBPyConnection) -> Portfolio:
    cur = conn.cursor()  # the API serves requests on threads
    try:
        head = cur.execute(
            "select max(features_as_of), count(*), sum(total_overdue), sum(expected_value),"
            " count(action), count(*) filter (where tier = 'red'), count(*) filter (where hardship),"
            " count(*) filter (where hard_stop) from nba.cards"
        ).fetchone()
        assert head is not None
        as_of, n, bal, ev, act, red, hard, stops = head
        ab = []
        for cell, cases, kept, promises, cured in cur.execute(SQL_AB).fetchall():
            kr, klo, khi = wilson(int(kept or 0), int(promises or 0))
            cr, clo, chi = wilson(int(cured or 0), int(cases))
            ab.append(
                Cell(
                    test_cell=cell,
                    cases=cases,
                    promises=int(promises or 0),
                    kept_rate=kr,
                    kept_lo=klo,
                    kept_hi=khi,
                    cure_rate=cr,
                    cure_lo=clo,
                    cure_hi=chi,
                )
            )
        cohorts = [
            CohortCell(
                quarter=q,
                product=prod,
                promises=int(m or 0),
                kept_rate=(int(k or 0) / int(m)) if m and m >= MIN_PROMISES else None,
            )
            for q, prod, k, m in cur.execute(SQL_COHORT).fetchall()
        ]
        p = Portfolio(
            as_of=as_of,
            cases=n,
            balance=float(bal or 0),
            expected=float(ev or 0),
            actionable=act,
            red=red,
            hardship=hard,
            hard_stops=stops,
            by_tier=_slices(cur, "tier"),
            by_action=_slices(cur, "action"),
            by_bucket=_slices(cur, "current_bucket"),
            ab_test=ab,
            cohorts=cohorts,
            insights=[],
            flow=_flow(cur),
        )
    finally:
        cur.close()
    return p.model_copy(update={"insights": _insights(p)})


def case_page(
    conn: duckdb.DuckDBPyConnection,
    *,
    offset: int = 0,
    limit: int = 50,
    sort: Sort = "expected_value",
    tier: str | None = None,
    action: str | None = None,
    bucket: str | None = None,
    q: str | None = None,
) -> CasePage:
    """One page of tonight's cards, filtered and sorted in SQL (96,000 rows: never all at once)."""
    if sort not in SORTS:
        raise ValueError(f"sort must be one of {SORTS}")
    where, params = ["true"], []  # type: ignore[var-annotated]
    for col, v in (("tier", tier), ("action", action), ("current_bucket", bucket)):
        if v == "none":
            where.append(f"{col} is null")
        elif v:
            where.append(f"{col} = ?")
            params.append(v)
    if q:
        where.append("(case_id ilike ? or display_name ilike ?)")
        params += [f"%{q}%", f"%{q}%"]
    w = " and ".join(where)
    cur = conn.cursor()
    try:
        total = cur.execute(f"select count(*) from nba.cards where {w}", params).fetchone()
        rows = cur.execute(
            "select case_id, display_name, current_bucket, max_dpd, total_overdue, action, tier, p_paid_14d,"
            f" expected_value, hardship, hard_stop from nba.cards where {w}"
            f" order by {sort} desc nulls last, case_id limit ? offset ?",
            [*params, limit, offset],
        ).fetchall()
    finally:
        cur.close()
    return CasePage(
        rows=[
            CaseRow(
                case_id=r[0],
                display_name=r[1],
                current_bucket=r[2],
                max_dpd=r[3],
                total_overdue=float(r[4]),
                action=r[5],
                tier=r[6],
                p_paid_14d=r[7],
                expected_value=float(r[8] or 0),
                hardship=bool(r[9]),
                hard_stop=bool(r[10]),
            )
            for r in rows
        ],
        total=int(total[0]) if total else 0,
    )


SQL_WORKLOAD_CALLS = (
    "select isodow(t) - 1, hour(t), count(*) from (select timezone(?, (card->>'$.proposal.window_start')"
    "::timestamptz) as t from nba.cards where card->>'$.proposal.channel' = 'call') where t is not null"
    " group by 1, 2"
)
# each hourly band's units (capacity less used) spread evenly over its hours; all_day bands aren't calls
SQL_WORKLOAD_CAPACITY = (
    "with c as (select date, greatest(capacity_units - coalesce(used_units, 0), 0) as units,"
    " split_part(time_band, '-', 1)::int as s, split_part(time_band, '-', 2)::int as e"
    " from silver.channel_capacity where channel = 'call' and time_band similar to '[0-9]+-[0-9]+'"
    " and date > (select max(date) from silver.channel_capacity where channel = 'call') - 7),"
    " h as (select date, unnest(range(s, e)) as hour, units / (e - s) as per from c where e > s)"
    " select isodow(date) - 1, hour, sum(per), min(min(date)) over (), max(max(date)) over ()"
    " from h group by 1, 2"
)


def workload(conn: duckdb.DuckDBPyConnection) -> Workload:
    """#115: proposed calls by the weekday and hour their window starts (operating time zone) against the
    latest week of call capacity. ponytail: a call counts in its start hour, not spread over its window."""
    cur = conn.cursor()
    try:
        rows = cur.execute(SQL_WORKLOAD_CALLS, [OPERATING_TZ]).fetchall()
        cap_rows = cur.execute(SQL_WORKLOAD_CAPACITY).fetchall()
    finally:
        cur.close()
    calls = {(int(d), int(h)): int(n) for d, h, n in rows}
    cap = {(int(d), int(h)): float(u) for d, h, u, _, _ in cap_rows}
    return Workload(
        time_zone=OPERATING_TZ,
        calls=sum(calls.values()),
        capacity_from=cap_rows[0][3] if cap_rows else None,
        capacity_to=cap_rows[0][4] if cap_rows else None,
        cells=[
            WorkloadCell(weekday=d, hour=h, calls=calls.get((d, h), 0), capacity=cap.get((d, h), 0.0))
            for d, h in sorted(calls.keys() | cap.keys())
        ],
    )
