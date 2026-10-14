"""The portfolio page: tonight's cards and the bank's own randomised test, summarised from the warehouse.

Every number on the page comes from one of the queries below, and each insight carries the SQL behind it, so a
reader can rerun it. Nothing is estimated here: the model's work is on the cards (nba.cards, from kept score).
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Literal

import duckdb
from pydantic import BaseModel

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
                title="The bank's strategies keep promises at the same rate"
                if overlap
                else "One strategy keeps promises at a different rate",
                body=f"Champion {champ.kept_rate:.1%} of {champ.promises:,} promises kept; {rates}. "
                + (
                    "Every 95% interval overlaps the champion's: channel and intensity don't move it;"
                    " timing does."
                    if overlap
                    else "At least one interval doesn't overlap the champion's."
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
                title=f"{red.balance / p.balance:.0%} of the balance at risk needs a specialist",
                body=f"{red.cases:,} Red cases hold ${red.balance:,.0f}: hardship or vulnerability, so each"
                " needs a "
                "hardship specialist and a second person before anything reaches the customer.",
                tone="warn",
                sql=SQL_SLICES.format(col="tier"),
            )
        )
    top = max(p.by_bucket, key=lambda s: s.expected, default=None)
    if top and p.expected:
        out.append(
            Insight(
                id="bucket",
                title=f"Most of tonight's expected recovery is in the {top.key} bucket",
                body=f"${top.expected:,.0f} of ${p.expected:,.0f} ({top.expected / p.expected:.0%}) across "
                f"{top.cases:,} cases: expected recovery is uplift over waiting times the balance.",
                tone="good",
                sql=SQL_SLICES.format(col="current_bucket"),
            )
        )
    if p.hard_stops:
        out.append(
            Insight(
                id="stops",
                title=f"{p.hard_stops:,} cases get no contact at all",
                body="Cease requests, insolvency holds and deceased flags stop contact before a model runs.",
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
