"""Charts for Ask answers (issue #100). Not wired into the Ask page yet: POST /chart and the /charts lab page.

Rules list every chart the result rows can honestly support (one axis, no invented numbers, at most
4 series). The LLM sees the question, the SQL that ran, a profile of each column and the first rows,
and only picks one of those options, or a table. Anything it gets wrong falls back to the rules' pick,
so a chart never depends on the free model being right.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field

from kept.common.llm import Purpose
from kept.contracts.enums import Role
from kept.contracts.interfaces import LLMGateway, Redactor

ChartKind = Literal["tile", "bar", "line", "grouped_bar", "table"]
Unit = Literal["fraction", "percent", "money", "count", "number"]
ColumnKind = Literal["number", "time", "category", "id", "text"]

MAX_BARS = 25  # more categories than this: a table reads better
MAX_SERIES = 4  # the palette's adjacent-safe slots; more series fold to a table
MAX_TILES = 4
LLM_ROWS = 12  # rows shown to the LLM; the profile covers every row

_NUM = re.compile(r"^-?\d+(\.\d+)?$")
_DATEISH = re.compile(r"^\d{4}-\d{2}(-\d{2})?([ T].*)?$")
_TIME_NAME = re.compile(r"(^|_)(date|month|week|day|year|quarter|period|ts)($|_)")
_ID_NAME = re.compile(r"(^|_)id$")
_COUNT_NAME = re.compile(
    r"^(n|count|cnt|num_.+|n_.+|.+_count|.+_cnt|attempts|cases|accounts|customers|promises)$"
)
_RATE_NAME = re.compile(r"(rate|share|ratio|pct|percent|_r$)")
_MONEY_NAME = re.compile(r"(amount|balance|cost|collected|overdue|paid|cad|dollar|value|spend)")


class ChartRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2_000)
    sql: str | None = None
    columns: list[str] = Field(max_length=50)
    rows: list[list[Any]] = Field(max_length=1_000)
    user_id: str
    role: Role


class ColumnProfile(BaseModel):
    name: str
    kind: ColumnKind
    unit: Unit | None = None  # numbers only
    distinct: int
    nulls: int
    low: float | None = None
    high: float | None = None


class ChartOption(BaseModel):
    """One chart the rows support. x / y / series are column names; y has one entry per series
    (several only when they share a unit: never two scales)."""

    id: str
    kind: ChartKind
    title: str
    x: str | None = None
    y: list[str] = Field(default_factory=list)
    series: str | None = None  # a category column that splits y into lines / grouped bars
    unit: Unit | None = None
    describe: str  # what the LLM reads, e.g. "bars: kept_rate by product (4 bars)"


class ChartChoice(BaseModel):
    option: ChartOption
    options: list[ChartOption]
    profile: list[ColumnProfile]
    source: Literal["llm", "rules"]
    why: str | None = None  # the LLM's one-line reason (no numbers), shown in the lab page


def num(v: Any) -> float | None:
    """A cell as a number. The API sends Decimals as strings, so '0.42' is 0.42; bools are not numbers."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, int | float | Decimal):
        return float(v)
    if isinstance(v, str) and _NUM.match(v.strip()):
        return float(v)
    return None


def _is_time_value(v: Any) -> bool:
    return isinstance(v, date | datetime) or (isinstance(v, str) and bool(_DATEISH.match(v.strip())))


def humanize(name: str) -> str:
    s = name.replace("_", " ").strip()
    return s[:1].upper() + s[1:]


def profile(columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> list[ColumnProfile]:
    out = []
    for j, name in enumerate(columns):
        cells = [r[j] if j < len(r) else None for r in rows]
        present = [c for c in cells if c is not None and c != ""]
        nulls, distinct = len(cells) - len(present), len({str(c) for c in present})
        key = name.lower()
        nums = [num(c) for c in present]
        if present and all(_is_time_value(c) for c in present):
            out.append(ColumnProfile(name=name, kind="time", distinct=distinct, nulls=nulls))
        elif present and all(n is not None for n in nums):
            vals = [n for n in nums if n is not None]
            lo, hi = min(vals), max(vals)
            if _ID_NAME.search(key):
                out.append(ColumnProfile(name=name, kind="id", distinct=distinct, nulls=nulls))
            elif _TIME_NAME.search(key) and key.endswith("year") and all(v.is_integer() for v in vals):
                out.append(ColumnProfile(name=name, kind="time", distinct=distinct, nulls=nulls))
            else:
                out.append(
                    ColumnProfile(
                        name=name,
                        kind="number",
                        unit=_unit(key, vals),
                        distinct=distinct,
                        nulls=nulls,
                        low=lo,
                        high=hi,
                    )
                )
        elif _ID_NAME.search(key):
            out.append(ColumnProfile(name=name, kind="id", distinct=distinct, nulls=nulls))
        else:
            long_text = any(isinstance(c, str) and len(c) > 60 for c in present)
            out.append(
                ColumnProfile(
                    name=name, kind="text" if long_text else "category", distinct=distinct, nulls=nulls
                )
            )
    return out


def _unit(key: str, vals: list[float]) -> Unit:
    if _RATE_NAME.search(key):
        return "fraction" if all(0 <= v <= 1 for v in vals) else "percent"
    if _COUNT_NAME.match(key) and all(v.is_integer() for v in vals):
        return "count"
    if _MONEY_NAME.search(key):
        return "money"
    return "number"


def chart_options(
    columns: Sequence[str], rows: Sequence[Sequence[Any]]
) -> tuple[list[ChartOption], list[ColumnProfile]]:
    """Every chart the rows support, best default first; a table is always the last option."""
    prof = profile(columns, rows)
    n = len(rows)
    measures = [p for p in prof if p.kind == "number"]
    measures.sort(key=lambda p: p.unit == "count")  # a rate or amount before a plain count
    times = [p for p in prof if p.kind == "time"]
    cats = [p for p in prof if p.kind == "category"]
    opts: list[ChartOption] = []

    def add(kind: ChartKind, title: str, describe: str, **kw: Any) -> None:
        opts.append(ChartOption(id=str(len(opts) + 1), kind=kind, title=title, describe=describe, **kw))

    if n == 1 and measures:
        tiles = measures[:MAX_TILES]
        names = ", ".join(p.name for p in tiles)
        add(
            "tile",
            humanize(tiles[0].name),
            f"number tile(s): {names}",
            y=[p.name for p in tiles],
            unit=tiles[0].unit,
        )
    if n >= 2:
        for t in times[:1]:
            one_row_each = t.distinct == n  # else several rows share a date: only a split by category works
            for m in measures if one_row_each else []:
                add(
                    "line",
                    f"{humanize(m.name)} by {t.name}",
                    f"line: {m.name} over {t.name} ({t.distinct} points)",
                    x=t.name,
                    y=[m.name],
                    unit=m.unit,
                )
            for m in measures[:1]:
                for c in cats:
                    if 2 <= c.distinct <= MAX_SERIES:
                        add(
                            "line",
                            f"{humanize(m.name)} by {t.name} and {c.name}",
                            f"lines: {m.name} over {t.name}, one line per {c.name} ({c.distinct} lines)",
                            x=t.name,
                            y=[m.name],
                            series=c.name,
                            unit=m.unit,
                        )
            same = _same_unit(measures)
            if one_row_each and len(same) >= 2:
                add(
                    "line",
                    f"{', '.join(humanize(m.name) for m in same)} by {t.name}",
                    f"lines: {', '.join(m.name for m in same)} over {t.name} (one line each)",
                    x=t.name,
                    y=[m.name for m in same],
                    unit=same[0].unit,
                )
        for c in cats:
            if c.distinct == n and 2 <= n <= MAX_BARS:
                for m in measures:
                    add(
                        "bar",
                        f"{humanize(m.name)} by {c.name}",
                        f"bars: {m.name} by {c.name} ({n} bars)",
                        x=c.name,
                        y=[m.name],
                        unit=m.unit,
                    )
                same = _same_unit(measures)
                if len(same) >= 2 and n <= 12:
                    add(
                        "grouped_bar",
                        f"{', '.join(humanize(m.name) for m in same)} by {c.name}",
                        f"grouped bars: {', '.join(m.name for m in same)} side by side for each {c.name}",
                        x=c.name,
                        y=[m.name for m in same],
                        unit=same[0].unit,
                    )
        if len(cats) >= 2 and measures and not times:
            a, b = cats[0], cats[1]
            for x, s in ((a, b), (b, a)):
                if 2 <= s.distinct <= MAX_SERIES and 2 <= x.distinct <= 12:
                    m = measures[0]
                    add(
                        "grouped_bar",
                        f"{humanize(m.name)} by {x.name} and {s.name}",
                        f"grouped bars: {m.name} by {x.name}, one bar per {s.name}",
                        x=x.name,
                        y=[m.name],
                        series=s.name,
                        unit=m.unit,
                    )
    add("table", "Table", "table: the rows as they are (no chart)")
    return opts, prof


def _same_unit(measures: list[ColumnProfile]) -> list[ColumnProfile]:
    """The first measure plus every other measure with its unit, up to MAX_SERIES. Counts don't group."""
    if not measures or measures[0].unit == "count":
        return []
    first = measures[0]
    return [m for m in measures if m.unit == first.unit][:MAX_SERIES]


_SYSTEM = """You choose how to show the result of a collections data question.
You get the question, the SQL that ran, a profile of each result column and the first rows, then a
numbered list of the charts this data supports. Pick the ONE option that best answers the question as
asked:
- change over time -> a line;
- comparing groups -> bars (grouped bars when the question compares two things per group);
- a single number -> the tile;
- many exact values, or nothing gains from a picture -> the table.
Chart the measure the question asks about (a rate, an amount), not a count column, unless the question
asks how many. You may only answer with an option number from the list.
"why" is one short sentence for an analyst, with no numbers in it."""

_SCHEMA = {
    "type": "object",
    "properties": {"option": {"type": "string"}, "why": {"type": "string"}},
    "required": ["option"],
}


def _prompt(req: ChartRequest, prof: list[ColumnProfile], opts: list[ChartOption]) -> str:
    cols = "\n".join(
        f"- {p.name}: {p.kind}"
        + (
            f", {p.unit}, from {p.low:g} to {p.high:g}"
            if p.kind == "number" and p.low is not None and p.high is not None
            else ""
        )
        + f", {p.distinct} distinct"
        + (f", {p.nulls} empty" if p.nulls else "")
        for p in prof
    )
    head = " | ".join(req.columns)
    body = "\n".join(" | ".join("" if c is None else str(c) for c in r) for r in req.rows[:LLM_ROWS])
    more = f"\n(... {len(req.rows) - LLM_ROWS} more rows)" if len(req.rows) > LLM_ROWS else ""
    listed = "\n".join(f"{o.id}. {o.describe}" for o in opts)
    sql = (req.sql or "(no SQL: certified metric or template)")[:1_500]
    return (
        f"Question: {req.question}\n\nSQL:\n{sql}\n\nColumns ({len(req.rows)} rows):\n{cols}\n\n"
        f"First rows:\n{head}\n{body}{more}\n\nOptions:\n{listed}"
    )


def choose_chart(
    req: ChartRequest, *, llm: LLMGateway | None = None, redactor: Redactor | None = None
) -> ChartChoice:
    """The rules' options, and the LLM's pick among them when an LLM and a redactor are given.
    Never raises on an LLM problem: a failed call, an unknown option or bad JSON gives the rules' pick."""
    opts, prof = chart_options(req.columns, req.rows)
    choice = ChartChoice(option=opts[0], options=opts, profile=prof, source="rules")
    if llm is None or redactor is None or len(opts) == 1:
        return choice
    try:
        reply = llm.complete(
            system=_SYSTEM,
            user=redactor.redact(_prompt(req, prof, opts)),
            purpose=Purpose.ASK_CHART,
            actor_id=req.user_id,
            json_schema=_SCHEMA,
        )
    except Exception:
        return choice
    parsed = reply.parsed or {}
    picked = next((o for o in opts if o.id == str(parsed.get("option", "")).strip().rstrip(".")), None)
    if picked is None:
        return choice
    why = str(parsed.get("why") or "").strip() or None
    if why and re.search(r"\d", why):  # numbers only ever come from the rows
        why = None
    return ChartChoice(option=picked, options=opts, profile=prof, source="llm", why=why)
