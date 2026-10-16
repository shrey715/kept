# ruff: noqa: E501
"""A1: warehouse engine and scale headroom. DuckDB (live) vs Polars, PostgreSQL and PySpark (local), three workloads, 1x/5x/10x.

Workloads (all read Parquet exported from data/warehouse/eval_copy.duckdb, read-only):
  silver_contact_history  dbt/models/silver/contact_history.sql (type casts of 2.7M rows x 131 columns)
  roll_rate               the certified query in src/kept/ask/certified.py (windows over silver.account_monthly_snapshot)
  account_history         the history half of dbt/models/features/account_features.sql (dpd, times_30plus, cash-flow trend)
Scale copies repeat every table with its ids suffixed (_k), so joins still match. Every run is a separate process in a
systemd scope (MemoryMax=8G, no swap); DuckDB memory_limit 4GB, 4 threads; Spark local[4] with 4g; Postgres in a 3g container.

    python scripts/decision_A1.py prepare 10        # export 1x Parquet and build 10 parts per table (needs data/a1_scratch)
    python scripts/decision_A1.py run               # every engine x workload x scale x 3 reps, appended to a1_runs.jsonl
    python scripts/decision_A1.py report            # JSON, figure
Run with the venv in data/a1_scratch/venv (duckdb, polars, pyspark, psycopg, sqlglot, matplotlib); see sections/A1.md.
"""

from __future__ import annotations

import argparse
import contextlib
import difflib
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(os.environ.get("KEPT_ROOT", "/home/akshat/hackathons/kept"))  # data/ is not in worktrees
REPO = Path(__file__).resolve().parents[1]
SCR = ROOT / "data" / "a1_scratch"
WH = ROOT / "data" / "warehouse" / "eval_copy.duckdb"
OUT = ROOT / "data" / "exports" / "reports" / "decision_A1.json"
RUNS = SCR / "a1_runs.jsonl"
PGPORT, PGNAME = 55432, "a1pg"
ENGINES = ["duckdb", "polars", "postgres", "spark"]
WORKLOADS = ["silver_contact_history", "roll_rate", "account_history"]

# table -> (warehouse relation, id columns that get the _k suffix in copy k)
TABLES = {
    "contact_history": ("bronze.contact_history", ["contact_id"]),
    "account_monthly_snapshot": ("silver.account_monthly_snapshot", ["account_id", "crm_customer_id"]),
    "feature_spine": ("features.feature_spine", ["case_id", "crm_customer_id"]),
    "identity_crosswalk": ("gold.identity_crosswalk", ["golden_customer_id", "source_key"]),
    "account_points": ("features.account_points", ["golden_customer_id", "account_id"]),
}
WL_TABLES = {
    "silver_contact_history": ["contact_history"],
    "roll_rate": ["account_monthly_snapshot"],
    "account_history": ["feature_spine", "identity_crosswalk", "account_points"],
}
# runs not made, with the reason (the scratch cap is 25 GB); filled from measured sizes of the smaller scales
SKIPS: dict[tuple[str, str, int], str] = {
    (
        "postgres",
        "roll_rate",
        10,
    ): "table would need about 32.6 GB (1x measured 3.26 GB, 5x measured 16.32 GB): above the 25 GB scratch cap",
    (
        "postgres",
        "silver_contact_history",
        10,
    ): "input plus output would need about 35 GB (1x measured 1.82 + 1.66 GB, 5x measured 9.11 + 8.30 GB): above the 25 GB scratch cap",
}
PG_SCHEMA = {"contact_history": "bronze", "account_monthly_snapshot": "silver"}  # others: public


# ---------------------------------------------------------------- SQL of the three workloads (DuckDB dialect)
def w1_sql() -> tuple[str, list[str]]:
    """The silver model with its source swapped for `src`, and the python UDF kept_date (no SQL equivalent) replaced by a plain
    cast on the two date columns (2 lines, the same in every engine). Returns (sql, output column names)."""
    t = (REPO / "dbt/models/silver/contact_history.sql").read_text()
    t = re.sub(r"\{#.*?#\}\n", "", t)
    t = t.replace("{{ source('bronze', 'contact_history') }}", "src")
    t = re.sub(r'coalesce\(try_cast\(("\w+") as DATE\), kept_date\(\1\)\)', r"try_cast(\1 as DATE)", t)
    return t, []


def w2_sql() -> str:
    q = (REPO / "src/kept/ask/certified.py").read_text()
    i = q.index('f"""WITH s AS')
    sql = q[i + 4 : q.index('"""', i + 8)]
    buckets = re.search(r'^_BUCKETS = "(.*)"$', q, re.M).group(1)
    sql = sql.replace("{_BUCKETS}", buckets)
    where = " AND start_rank > 0 AND end_dpd IS NOT NULL AND date_diff('month', month_end_date, end_date) = 3"
    return (
        sql.replace("{{group_by_select}}", "product_type,")
        .replace("{{where}}", where)
        .replace("{{group_by}}", "GROUP BY product_type")
    )


def w3_sql() -> str:
    t = (REPO / "dbt/models/features/account_features.sql").read_text()
    body = t[t.index("with spine as (") : t.index("payroll_account as (")].rstrip().rstrip(",")
    body = re.sub(r"\{\{ ref\('(\w+)'\) \}\}", r"\1", body)
    return (
        body
        + """
select s.case_id, s.as_of, q.max_dpd,
       case when q.max_dpd is not null then coalesce(t.times_30plus_dpd_12m, 0) end as times_30plus_dpd_12m,
       r.cash_flow_trend, r.card_utilisation_trend
from spine s
left join delinquency q using (case_id, as_of)
left join times_30 t using (case_id, as_of)
left join trends r using (case_id, as_of)"""
    )


# ---------------------------------------------------------------- dialect translation and manual patches
def _pg_try_cast(node):
    import sqlglot.expressions as exp

    if isinstance(node, exp.TryCast):
        base = node.args["to"].this.name.lower()
        base = {
            "bigint": "bigint",
            "boolean": "boolean",
            "timestamp": "timestamp",
            "timestampntz": "timestamp",
            "decimal": "numeric",
            "date": "date",
        }[base]
        return exp.Cast(
            this=exp.Anonymous(this=f"kept_try_{base}", expressions=[node.this]), to=node.args["to"]
        )
    return node


PG_FUNCS = [  # PostgreSQL has no TRY_CAST: one guarded function per target type (written by hand)
    "create or replace function kept_try_bigint(t text) returns bigint language sql immutable parallel safe as $$ select case when t ~ '^[+-]?[0-9]+$' then t::bigint end $$",
    "create or replace function kept_try_numeric(t text) returns numeric language sql immutable parallel safe as $$ select case when t ~ '^[+-]?([0-9]+[.]?[0-9]*|[.][0-9]+)$' then t::numeric end $$",
    "create or replace function kept_try_boolean(t text) returns boolean language sql immutable parallel safe as $$ select case lower(t) when 'true' then true when 'false' then false end $$",
    "create or replace function kept_try_timestamp(t text) returns timestamp language sql immutable parallel safe as $$ select case when t ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}([ T][0-9]{2}:[0-9]{2}:[0-9]{2}([.][0-9]+)?)?$' then t::timestamp end $$",
    "create or replace function kept_try_date(t text) returns date language sql immutable parallel safe as $$ select case when t ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' then t::date end $$",
]
# (sqlglot output fragment, hand-written replacement) per engine; only fragments sqlglot cannot translate
PATCH = {
    ("roll_rate", "postgres"): [
        (
            r"""NOT COALESCE\(\s*TRY_STRPTIME\(month_end_date_raw, '%Y-%m-%d'\),\s*TRY_STRPTIME\(month_end_date_raw, '%d/%m/%Y'\),\s*TRY_STRPTIME\(month_end_date_raw, '%Y%m%d'\)\s*\) IS NULL""",
            "(month_end_date_raw ~ '^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$' OR month_end_date_raw ~ '^(0[1-9]|[12][0-9]|3[01])/(0[1-9]|1[0-2])/[0-9]{4}$' OR month_end_date_raw ~ '^[0-9]{4}(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])$')",
        ),
        (
            r"LIST_EXTRACT\(\s*(ARRAY\[[^\]]*\]),\s*(LEAST\(7, DIV\(\(\s*dpd \+ 29\s*\), 30\)\)) \+ 1\s*\)",
            r"(\1)[\2 + 1]",
        ),
        (
            r"CAST\(EXTRACT\(year FROM AGE\(CAST\(end_date AS TIMESTAMP\), CAST\(month_end_date AS TIMESTAMP\)\)\) \* 12 \+ EXTRACT\(month FROM AGE\(CAST\(end_date AS TIMESTAMP\), CAST\(month_end_date AS TIMESTAMP\)\)\) AS BIGINT\)",
            "(extract(year from end_date) - extract(year from month_end_date)) * 12 + extract(month from end_date) - extract(month from month_end_date)",
        ),  # sqlglot's AGE counts whole months: 31 Jan to 30 Apr is 2, DuckDB date_diff says 3
    ],
    ("roll_rate", "spark"): [
        (
            r"""NOT COALESCE\(\s*TRY_STRPTIME\(month_end_date_raw, '%Y-%m-%d'\),\s*TRY_STRPTIME\(month_end_date_raw, '%d/%m/%Y'\),\s*TRY_STRPTIME\(month_end_date_raw, '%Y%m%d'\)\s*\) IS NULL""",
            "NOT COALESCE(try_to_date(month_end_date_raw, 'yyyy-MM-dd'), try_to_date(month_end_date_raw, 'dd/MM/yyyy'), try_to_date(month_end_date_raw, 'yyyyMMdd')) IS NULL",
        ),
        (
            r"LIST_EXTRACT\(\s*(ARRAY\([^)]*\)),\s*(LEAST\(7, \(\s*dpd \+ 29\s*\) DIV 30\)) \+ 1\s*\)",
            r"element_at(\1, CAST(\2 + 1 AS INT))",
        ),
        (
            r"DATEDIFF\(MONTH, month_end_date, end_date\)",
            "(year(end_date) - year(month_end_date)) * 12 + month(end_date) - month(month_end_date)",
        ),  # Spark counts whole months too
    ],
    ("account_history", "postgres"): [
        (r"ARG_MAX\((\w+), (\w+)\)", r"(array_agg(\1 order by \2 desc))[1]"),
        (r"ROUND\(REGR_SLOPE\(([^)]*)\), 9\)", r"ROUND((REGR_SLOPE(\1))::numeric, 9)"),
    ],
    ("account_history", "spark"): [
        (r"ANY_VALUE\(d\)( IGNORE NULLS)? - MAX\(point_date\)", "DATEDIFF(ANY_VALUE(d), MAX(point_date))"),
    ],
}


def sql_for(workload: str, engine: str) -> tuple[str, int]:
    """(sql for the engine, number of lines changed by hand after sqlglot). DuckDB is the source dialect: 0."""
    import sqlglot

    base = {"silver_contact_history": w1_sql()[0], "roll_rate": w2_sql(), "account_history": w3_sql()}[
        workload
    ]
    if engine == "duckdb":
        return base, 0
    dialect = {"postgres": "postgres", "spark": "spark"}[engine]
    tree = sqlglot.parse_one(base, read="duckdb")
    if engine == "postgres":
        tree = tree.transform(_pg_try_cast)
    glot = tree.sql(dialect=dialect, pretty=True)
    final = glot
    for pat, rep in PATCH.get((workload, engine), []):
        final, n = re.subn(pat, rep, final, flags=re.S | re.I)
        if n == 0:
            raise RuntimeError(f"patch did not match: {workload}/{engine}: {pat[:50]}")
    extra = 0
    if workload == "silver_contact_history":
        # DuckDB's `select * exclude (channel_v2) replace (...)` has no PG/Spark spelling: expand the column list by hand (1 line)
        cols = _w1_columns()
        final = re.sub(
            r"SELECT\s+\*.*FROM typed\s*$",
            "SELECT "
            + ", ".join("COALESCE(channel_v2, channel) AS channel" if c == "channel" else c for c in cols)
            + " FROM typed",
            final,
            flags=re.I | re.S,
        )
        extra = (
            2  # the two kept_date lines (python UDF -> plain cast); the select list counts through the diff
        )
        if engine == "postgres":
            extra += len(PG_FUNCS)  # the five helper functions
    ndiff = sum(1 for ln in difflib.ndiff(glot.splitlines(), final.splitlines()) if ln.startswith("+ "))
    return final, ndiff + extra


def _w1_columns() -> list[str]:
    t = w1_sql()[0]
    sel = t[t.index("select\n") + 7 : t.index("    from src")]
    cols = []
    for ln in sel.splitlines():
        ln = ln.strip().rstrip(",")
        m = re.search(r' as "(\w+)"$', ln) or re.fullmatch(r'"?(\w+)"?', ln)
        cols.append(m.group(1))
    return [c for c in cols if c != "channel_v2"]  # the model's output drops it


# ---------------------------------------------------------------- data preparation
def duck(mem="4GB"):
    import duckdb

    c = duckdb.connect()
    c.execute(f"set memory_limit='{mem}'; set threads=4; set temp_directory='{SCR / 'tmp_prep'}'")
    return c


def parts_dir(table: str, scale: int) -> Path:
    return SCR / f"p{scale}x" / table


def part_files(table: str, scale: int) -> list[str]:
    return sorted(str(p) for p in parts_dir(table, scale).glob("part_*.parquet"))


def prepare(n: int, tables: list[str] | None = None, start: int = 0) -> None:
    """Export 1x from the warehouse once, then write parts start..n-1 (ids suffixed _k) and hardlink them into p{1,5,10}x."""
    import duckdb

    base = SCR / "base"
    base.mkdir(parents=True, exist_ok=True)
    c = duck()
    for t, (rel, ids) in TABLES.items():
        if tables and t not in tables:
            continue
        b = base / f"{t}.parquet"
        if not b.exists():
            w = duckdb.connect(str(WH), read_only=True)
            w.execute("set memory_limit='4GB'; set threads=4")
            w.execute(
                f"copy (select * from {rel}) to '{b}' (format parquet, compression zstd, row_group_size 122880)"
            )
            w.close()
        rep = ", ".join(f'"{i}" || \'_{{k}}\' as "{i}"' for i in ids)
        for k in range(start, n):
            d = SCR / "parts" / t
            d.mkdir(parents=True, exist_ok=True)
            f = d / f"part_{k:03d}.parquet"
            if not f.exists():
                c.execute(
                    f"copy (select * replace ({rep.format(k=k)}) from read_parquet('{b}')) to '{f}' (format parquet, compression zstd, row_group_size 122880)"
                )
    link_scales(n)


def link_scales(n: int, scales=(1, 5, 10, 20, 40, 80)) -> None:
    for t in TABLES:
        src = SCR / "parts" / t
        if not src.exists():
            continue
        have = sorted(src.glob("part_*.parquet"))
        for s in scales:
            if s > len(have):
                continue
            d = SCR / f"p{s}x" / t
            d.mkdir(parents=True, exist_ok=True)
            for f in have[:s]:
                if not (d / f.name).exists():
                    os.link(f, d / f.name)


def dir_bytes(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


# ---------------------------------------------------------------- workers: one engine, one workload, one scale, one repetition
def check_sql_w1(cols: list[str], rel: str) -> str:
    return "select count(*), " + " + ".join(f'count("{c}")' for c in cols) + f" from {rel}"


def worker(engine: str, workload: str, scale: int, reps: int) -> dict:
    out = {"engine": engine, "workload": workload, "scale": scale}
    tdir = SCR / f"tmp_{engine}_{os.getpid()}"
    tdir.mkdir(exist_ok=True)
    try:
        res = globals()[f"run_{engine}"](workload, scale, tdir, reps)
    finally:
        shutil.rmtree(tdir, ignore_errors=True)
    out.update(res)
    return out


def _dd_check(rel_or_sql: str, workload: str, c) -> object:
    if workload == "silver_contact_history":
        return c.execute(rel_or_sql).fetchall()[0]
    if workload == "roll_rate":
        return [(p, round(r, 6), n) for p, r, n in c.execute(rel_or_sql).fetchall()]
    return list(c.execute(rel_or_sql).fetchall()[0])


def check_queries(workload: str, src: str) -> str:
    """DuckDB-dialect check over an output relation (a parquet path or a table name)."""
    if workload == "silver_contact_history":
        return check_sql_w1(_w1_columns(), src)
    if workload == "roll_rate":
        return f"select product_type, roll_rate, n from {src} order by product_type"
    return f"select count(*), sum(max_dpd), sum(times_30plus_dpd_12m), round(sum(cash_flow_trend), 4), round(sum(card_utilisation_trend), 4) from {src}"


def run_duckdb(workload, scale, tdir, reps):
    import duckdb

    c = duckdb.connect(str(tdir / "w.duckdb"))
    c.execute(f"set memory_limit='4GB'; set threads=4; set temp_directory='{tdir / 'spill'}'")
    for t in WL_TABLES[workload]:
        files = part_files(t, scale)
        name = "src" if workload == "silver_contact_history" else t
        schema = PG_SCHEMA.get(t)
        if schema and workload != "silver_contact_history":
            c.execute(f"create schema if not exists {schema}")
            name = f"{schema}.{t}"
        c.execute(f"create view {name} as select * from read_parquet({files})")
    sql, _ = sql_for(workload, "duckdb")
    t0 = time.perf_counter()
    if workload == "silver_contact_history":
        c.execute(f"create table out as {sql}")
        c.execute("checkpoint")
        res = _dd_check(check_sql_w1(_w1_columns(), "out"), workload, c)
        t1 = time.perf_counter()
    else:
        o = tdir / "out.parquet"
        c.execute(f"copy ({sql}) to '{o}' (format parquet)")
        t1 = time.perf_counter()
        res = _dd_check(check_queries(workload, f"'{o}'"), workload, c)
    wall = t1 - t0
    disk = (
        (tdir / "w.duckdb").stat().st_size
        if workload == "silver_contact_history"
        else dir_bytes(tdir / "out.parquet")
    )
    return {"wall_s": [wall], "check": res, "out_bytes": disk}


def run_polars(workload, scale, tdir, reps):
    import polars as pl

    t0 = time.perf_counter()
    if workload == "silver_contact_history":
        lf = pl.scan_parquet(part_files("contact_history", scale))
        sql_, _ = sql_for(workload, "duckdb")
        exprs = polars_w1_exprs(sql_)
        o = tdir / "out.parquet"
        lf.select(exprs).sink_parquet(o)
        src = f"'{o}'"
    elif workload == "roll_rate":
        o = tdir / "out.parquet"
        polars_w2(part_files("account_monthly_snapshot", scale)).write_parquet(o)
        src = f"'{o}'"
    else:
        o = tdir / "out.parquet"
        polars_w3(*(part_files(t, scale) for t in WL_TABLES[workload])).write_parquet(o)
        src = f"'{o}'"
    wall = time.perf_counter() - t0
    c = duck("1GB")
    res = _dd_check(check_queries(workload, src), workload, c)
    return {"wall_s": [wall], "check": res, "out_bytes": dir_bytes(o)}


def polars_w1_exprs(sql_: str):
    """The casts of the silver model as Polars expressions (read off the model with sqlglot; the select list is rewritten by hand)."""
    import polars as pl
    import sqlglot
    import sqlglot.expressions as exp

    tree = sqlglot.parse_one(sql_, read="duckdb")
    typed = next(cte for cte in tree.find_all(exp.CTE) if cte.alias == "typed")
    out = []
    for e in typed.this.expressions:
        name = e.alias_or_name
        inner = e.this if isinstance(e, exp.Alias) else e
        col = pl.col(
            name
            if isinstance(e, exp.Alias) and isinstance(inner, exp.Column) is False
            else inner.name
            if isinstance(inner, exp.Column)
            else name
        )
        if isinstance(inner, exp.TryCast):
            src = pl.col(inner.this.name)
            t = inner.args["to"].this
            if t == exp.DType.BIGINT:
                col = src.cast(pl.Int64, strict=False)
            elif t == exp.DType.BOOLEAN:
                col = src.str.to_lowercase().replace_strict(
                    {"true": True, "false": False}, default=None, return_dtype=pl.Boolean
                )
            elif t in (exp.DType.TIMESTAMP, exp.DType.TIMESTAMPNTZ):
                col = src.str.to_datetime(strict=False)
            elif t == exp.DType.DATE:
                col = src.str.to_date(strict=False)
            elif t == exp.DType.DECIMAL:
                p, s = (int(x.this.name) for x in inner.args["to"].expressions)
                col = src.cast(pl.Decimal(p, s), strict=False)
            else:
                raise RuntimeError(t)
        out.append(col.alias(name))
    names = [x.meta.output_name() for x in out]
    ch = names.index("channel")
    out[ch] = pl.coalesce(pl.col("channel_v2"), pl.col("channel")).alias("channel")
    return [x for x, n in zip(out, names, strict=True) if n != "channel_v2"]


def polars_w2(files):
    import polars as pl

    d = pl.col("month_end_date_raw")
    parsed = pl.coalesce(
        d.str.to_date("%Y-%m-%d", strict=False),
        d.str.to_date("%d/%m/%Y", strict=False),
        d.str.to_date("%Y%m%d", strict=False),
    )
    lf = (
        pl.scan_parquet(files)
        .filter(
            pl.col("dpd").is_not_null() & ~pl.col("write_off_flag").fill_null(False) & parsed.is_not_null()
        )
        .select(
            "product_type",
            "month_end_date",
            "dpd",
            end_dpd=pl.col("dpd").shift(-1).over("account_id", order_by="month_end_date"),
            end_date=pl.col("month_end_date").shift(-1).over("account_id", order_by="month_end_date"),
        )
        .with_columns(
            start_rank=pl.min_horizontal(pl.lit(7), (pl.col("dpd") + 29) // 30),
            end_rank=pl.min_horizontal(pl.lit(7), (pl.col("end_dpd") + 29) // 30),
        )
        .filter(
            (pl.col("start_rank") > 0)
            & pl.col("end_dpd").is_not_null()
            & (
                (pl.col("end_date").dt.year() * 12 + pl.col("end_date").dt.month())
                - (pl.col("month_end_date").dt.year() * 12 + pl.col("month_end_date").dt.month())
                == 3
            )
        )
        .group_by("product_type")
        .agg(roll_rate=(pl.col("end_rank") > pl.col("start_rank")).cast(pl.Float64).mean(), n=pl.len())
    )
    return lf.collect(engine="streaming")


def polars_w3(spine_f, cw_f, pts_f):
    import polars as pl

    cw = (
        pl.scan_parquet(cw_f)
        .filter((pl.col("source_system") == "collections") & pl.col("valid_to").is_null())
        .select("golden_customer_id", "source_key")
    )
    spine = (
        pl.scan_parquet(spine_f)
        .join(cw, left_on="crm_customer_id", right_on="source_key")
        .select("case_id", "as_of", d=pl.col("as_of").dt.date(), golden_customer_id="golden_customer_id")
    )
    known = spine.join(pl.scan_parquet(pts_f), on="golden_customer_id").filter(
        pl.col("point_date") <= pl.col("d")
    )
    kind_cl = pl.col("kind").is_in(["card", "loan"])
    since = pl.col("point_date") > pl.col("d").dt.offset_by("-12mo")
    dpd_now = (
        known.filter(kind_cl & pl.col("dpd").is_not_null())
        .group_by("case_id", "as_of", "account_id")
        .agg(
            a=pl.col("dpd").sort_by("point_date").last(), mp=pl.col("point_date").max(), d=pl.col("d").first()
        )
        .with_columns(gap=(pl.col("d") - pl.col("mp")).dt.total_days())
        .with_columns(
            dpd=pl.col("a")
            + pl.when((pl.col("a") > 0) & (pl.col("gap") <= 31)).then(pl.col("gap")).otherwise(0)
        )
    )
    delinq = dpd_now.group_by("case_id", "as_of").agg(max_dpd=pl.col("dpd").max())
    times30 = (
        known.filter(pl.col("month_end") & kind_cl & (pl.col("dpd") >= 30) & since)
        .group_by("case_id", "as_of")
        .agg(times_30plus_dpd_12m=pl.col("point_date").n_unique())
    )
    dep = pl.col("kind") == "deposit"
    monthly = (
        known.filter(pl.col("month_end") & since)
        .group_by("case_id", "as_of", "point_date")
        .agg(
            ncf_n=pl.col("net_cash_flow").filter(dep).count(),
            ncf_s=pl.col("net_cash_flow").filter(dep).sum(),
            utilisation=pl.col("utilisation").filter(pl.col("kind") == "card").mean(),
        )
        .with_columns(
            m=pl.col("point_date").dt.year() * 12
            + pl.col("point_date").dt.month()
            - 24000,  # months since 2000, as DuckDB date_diff gives (keeps the sums small)
            net=pl.when(pl.col("ncf_n") > 0).then(pl.col("ncf_s")),
        )
    )

    def slope(y: str):
        ok = pl.col(y).is_not_null()
        n, sx, sy = ok.sum(), pl.col("m").filter(ok).sum(), pl.col(y).filter(ok).sum()
        sxy, sxx = (pl.col("m") * pl.col(y)).filter(ok).sum(), (pl.col("m") * pl.col("m")).filter(ok).sum()
        return pl.when(n >= 3).then(((n * sxy - sx * sy) / (n * sxx - sx * sx)).round(9))

    trends = monthly.group_by("case_id", "as_of").agg(
        cash_flow_trend=slope("net"), card_utilisation_trend=slope("utilisation")
    )
    out = (
        spine.select("case_id", "as_of")
        .join(delinq, on=["case_id", "as_of"], how="left")
        .join(times30, on=["case_id", "as_of"], how="left")
        .join(trends, on=["case_id", "as_of"], how="left")
        .with_columns(
            times_30plus_dpd_12m=pl.when(pl.col("max_dpd").is_not_null()).then(
                pl.col("times_30plus_dpd_12m").fill_null(0)
            )
        )
        .select(
            "case_id", "as_of", "max_dpd", "times_30plus_dpd_12m", "cash_flow_trend", "card_utilisation_trend"
        )
    )
    return out.collect(engine="streaming")


def run_spark(workload, scale, tdir, reps):
    from pyspark.sql import SparkSession

    spark = (
        SparkSession.builder.master("local[4]")
        .appName("a1")
        .config("spark.driver.memory", "4g")
        .config("spark.local.dir", str(tdir / "sparklocal"))
        .config("spark.ui.enabled", "false")
        .config("spark.sql.shuffle.partitions", "16")
        .config("spark.driver.bindAddress", "127.0.0.1")
        .config("spark.driver.host", "127.0.0.1")
        .config("spark.sql.session.timeZone", "UTC")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("ERROR")
    for t in WL_TABLES[workload]:
        df = spark.read.parquet(*part_files(t, scale))
        if workload == "silver_contact_history":
            df.createOrReplaceTempView("src")
        else:
            schema = PG_SCHEMA.get(t)
            if schema:
                spark.sql(f"create database if not exists {schema}")
                spark.sql(f"create table {schema}.{t} using parquet location '{parts_dir(t, scale)}'")
            else:
                df.createOrReplaceTempView(t)
    sql, _ = sql_for(workload, "spark")
    o = tdir / "out"
    t0 = time.perf_counter()
    spark.sql(sql).write.mode("overwrite").parquet(str(o))
    wall = time.perf_counter() - t0
    spark.stop()
    c = duck("1GB")
    res = _dd_check(check_queries(workload, f"read_parquet('{o}/*.parquet')"), workload, c)
    return {"wall_s": [wall], "check": res, "out_bytes": dir_bytes(o)}


# ---- PostgreSQL
def pg():
    import psycopg

    return psycopg.connect(
        f"host=127.0.0.1 port={PGPORT} user=postgres password=a1 dbname=postgres", autocommit=True
    )


def pg_load(cur, table: str, scale: int) -> float:
    """COPY the parts of one table into Postgres through CSV (one part at a time, so scratch disk stays small)."""
    schema = PG_SCHEMA.get(table, "public")
    cur.execute("create table if not exists public.a1_loaded (tbl text primary key, scale int)")
    cur.execute("select scale from public.a1_loaded where tbl = %s", (table,))
    row = cur.fetchone()
    if row and row[0] == scale:
        return 0.0
    t0 = time.perf_counter()
    cur.execute(f"create schema if not exists {schema}")
    cur.execute(f"drop table if exists {schema}.{table}")
    cur.execute("delete from public.a1_loaded where tbl = %s", (table,))
    files = part_files(table, scale)
    c = duck("2GB")
    tmap = {
        "VARCHAR": "text",
        "BIGINT": "bigint",
        "DOUBLE": "double precision",
        "DATE": "date",
        "BOOLEAN": "boolean",
        "TIMESTAMP": "timestamp",
        "TIMESTAMP WITH TIME ZONE": "timestamptz",
    }
    cols = []
    for name, typ, *_ in c.execute(f"describe select * from read_parquet('{files[0]}')").fetchall():
        m = re.fullmatch(r"DECIMAL\((\d+),(\d+)\)", typ)
        cols.append(f'"{name}" ' + (f"numeric({m.group(1)},{m.group(2)})" if m else tmap[typ]))
    cur.execute(f"create unlogged table {schema}.{table} ({', '.join(cols)})")
    for f in files:
        csv = SCR / "pgcsv" / "x.csv"
        c.execute(f"copy (select * from read_parquet('{f}')) to '{csv}' (format csv, header false)")
        cur.execute(f"copy {schema}.{table} from '/csv/x.csv' (format csv)")
        csv.unlink()
    cur.execute(f"analyze {schema}.{table}")
    cur.execute("insert into public.a1_loaded values (%s, %s)", (table, scale))
    return time.perf_counter() - t0


def run_postgres(workload, scale, tdir, reps):
    cx = pg()
    cur = cx.cursor()
    cur.execute("set timezone = 'UTC'")
    for fn in PG_FUNCS:
        cur.execute(fn)
    cur.execute("create table if not exists public.a1_loaded (tbl text primary key, scale int)")
    cur.execute("select tbl from public.a1_loaded")
    for (t,) in cur.fetchall():  # keep only this workload's tables on disk
        if t not in WL_TABLES[workload]:
            cur.execute(f"drop table if exists {PG_SCHEMA.get(t, 'public')}.{t}")
            cur.execute("delete from public.a1_loaded where tbl = %s", (t,))
    load = sum(pg_load(cur, t, scale) for t in WL_TABLES[workload])
    cur.execute("set search_path = silver, bronze, public")
    cur.execute("set max_parallel_workers_per_gather = 4")
    sql, _ = sql_for(workload, "postgres")
    if workload == "silver_contact_history":
        sql = re.sub(r"\bFROM src\b", "FROM bronze.contact_history", sql, flags=re.I)
    walls = []
    for _ in range(reps):
        cur.execute("drop table if exists public.a1_out")
        t0 = time.perf_counter()
        cur.execute(f"create unlogged table public.a1_out as {sql}")
        walls.append(time.perf_counter() - t0)
    cur.execute("select pg_total_relation_size('public.a1_out')")
    out_bytes = cur.fetchone()[0]
    db_bytes = 0
    for t in WL_TABLES[workload]:
        cur.execute(f"select pg_total_relation_size('{PG_SCHEMA.get(t, 'public')}.{t}')")
        db_bytes += cur.fetchone()[0]
    if workload == "silver_contact_history":
        cur.execute(check_sql_w1(_w1_columns(), "public.a1_out"))
        res = cur.fetchone()
    elif workload == "roll_rate":
        cur.execute("select product_type, roll_rate, n from public.a1_out order by product_type")
        res = [(p, round(float(r), 6), n) for p, r, n in cur.fetchall()]
    else:
        cur.execute(
            "select count(*), sum(max_dpd), sum(times_30plus_dpd_12m), round(sum(cash_flow_trend)::numeric, 4), round(sum(card_utilisation_trend)::numeric, 4) from public.a1_out"
        )
        res = list(cur.fetchone())
    cur.execute("drop table public.a1_out")
    res = [float(x) if hasattr(x, "as_tuple") else x for x in res] if workload != "roll_rate" else res
    return {"wall_s": walls, "load_s": load, "check": res, "out_bytes": out_bytes, "db_bytes": db_bytes}


# ---------------------------------------------------------------- orchestrator
def tree_rss_mb(pid: int) -> float:
    """Sum of VmRSS over the process and its descendants (/proc), in MB."""
    kids: dict[int, list[int]] = {}
    for d in os.listdir("/proc"):
        if d.isdigit():
            try:
                st = Path(f"/proc/{d}/stat").read_text()
                kids.setdefault(int(st.rsplit(")", 1)[1].split()[1]), []).append(int(d))
            except OSError:
                pass
    todo, tot = [pid], 0.0
    while todo:
        p = todo.pop()
        todo += kids.get(p, [])
        try:
            for ln in Path(f"/proc/{p}/status").read_text().splitlines():
                if ln.startswith("VmRSS:"):
                    tot += int(ln.split()[1]) / 1024
        except OSError:
            pass
    return tot


def pg_mem_mb() -> float:
    r = subprocess.run(
        ["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", PGNAME],
        capture_output=True,
        text=True,
    )
    m = re.match(r"([\d.]+)\s*(\w+)", r.stdout.strip())
    return (
        float(m.group(1))
        * {"B": 1e-6, "kB": 1e-3, "KB": 1e-3, "MB": 1, "MiB": 1.05, "GB": 1000, "GiB": 1074}[m.group(2)]
        if m
        else 0.0
    )


def spawn(engine: str, workload: str, scale: int, reps: int, timeout: int) -> dict:
    cmd = [
        "systemd-run",
        "--user",
        "--scope",
        "-q",
        "-p",
        "MemoryMax=8G",
        "-p",
        "MemorySwapMax=0",
        "--",
        sys.executable,
        str(Path(__file__).resolve()),
        "worker",
        engine,
        workload,
        str(scale),
        str(reps),
    ]
    env = {**os.environ, "KEPT_ROOT": str(ROOT)}
    t0 = time.time()
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    peak, spill, stop = [0.0], [0], threading.Event()

    def sample():
        while not stop.is_set():
            peak[0] = max(peak[0], pg_mem_mb() if engine == "postgres" else tree_rss_mb(p.pid))
            with contextlib.suppress(OSError):
                spill[0] = max(
                    spill[0],
                    sum(
                        dir_bytes(d)
                        for d in SCR.glob(
                            f"tmp_{engine}_*/" + ("sparklocal" if engine == "spark" else "spill")
                        )
                    ),
                )
            stop.wait(0.0 if engine == "postgres" else 0.2)

    th = threading.Thread(target=sample, daemon=True)
    th.start()
    try:
        out, err = p.communicate(timeout=timeout)
        status = (
            "ok"
            if p.returncode == 0
            else "oom"
            if p.returncode in (-9, 137)
            or "OutOfMemory" in err
            or "MemoryError" in err
            or "Out of Memory" in err
            else "error"
        )
    except subprocess.TimeoutExpired:
        subprocess.run(["pkill", "-9", "-P", str(p.pid)])
        p.kill()
        out, err = p.communicate()
        status = "timeout"
    stop.set()
    th.join()
    rec = {
        "engine": engine,
        "workload": workload,
        "scale": scale,
        "status": status,
        "peak_rss_mb": round(peak[0]),
        "spill_bytes": spill[0],
        "total_proc_s": round(time.time() - t0, 1),
    }
    for ln in out.splitlines():
        if ln.startswith("A1RESULT "):
            rec.update(json.loads(ln[9:]))
    if status != "ok":
        rec["stderr_tail"] = err[-600:]
    return rec


def run_all(scales, engines, workloads, reps=3, timeout=3600, slow_s=300) -> None:
    for wl in workloads:
        for s in scales:
            for eng in engines:
                done = [json.loads(x) for x in RUNS.read_text().splitlines()] if RUNS.exists() else []
                if any(r["engine"] == eng and r["workload"] == wl and r["scale"] == s for r in done):
                    continue
                if (eng, wl, s) in SKIPS:
                    print(wl, s, eng, "skipped:", SKIPS[(eng, wl, s)])
                    continue
                recs: list[dict] = []
                if eng == "postgres":
                    recs.append(spawn(eng, wl, s, reps, timeout))
                else:
                    for _ in range(reps):
                        r = spawn(eng, wl, s, 1, timeout)
                        recs.append(r)
                        if r["status"] != "ok" or r.get("wall_s", [0])[0] > slow_s:
                            break  # a failure repeats exactly; a run above slow_s is measured once
                with RUNS.open("a") as f:
                    for r in recs:
                        f.write(json.dumps(r, default=str) + "\n")
                print(
                    wl,
                    s,
                    eng,
                    [r["status"] for r in recs],
                    [round(x, 1) for r in recs for x in r.get("wall_s", [])],
                    recs[-1]["peak_rss_mb"],
                    flush=True,
                )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["prepare", "run", "worker", "report", "sql"])
    ap.add_argument("args", nargs="*")
    a = ap.parse_args()
    if a.cmd == "prepare":
        prepare(int(a.args[0]), a.args[1:] or None)
    elif a.cmd == "worker":
        e, w, s, r = a.args
        print("A1RESULT " + json.dumps(worker(e, w, int(s), int(r)), default=str))
    elif a.cmd == "sql":
        print(sql_for(a.args[0], a.args[1]))
    elif a.cmd == "run":
        run_all([int(x) for x in a.args[0].split(",")], a.args[1].split(","), a.args[2].split(","))
    else:
        report()


def _same(a, b) -> bool:
    """Equal counts; rates and sums within 2e-5 (Spark types the literal 1.0 as a decimal, so its rates carry 5 decimals)."""
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b, strict=True))
    try:
        x, y = float(a), float(b)
    except (TypeError, ValueError):
        return a == b
    if not isinstance(a, str) and x == round(x) and y == round(y):
        return x == y  # counts and whole sums must be exact
    return abs(x - y) <= 2e-5 * max(1.0, abs(x), abs(y))


def load_runs() -> dict:
    recs = [json.loads(x) for x in RUNS.read_text().splitlines()]
    cells: dict = {}
    for r in recs:
        c = cells.setdefault((r["engine"], r["workload"], r["scale"]), {"walls": [], "recs": []})
        c["recs"].append(r)
        c["walls"] += r.get("wall_s", []) if r["status"] == "ok" else []
    return cells


def report() -> None:
    sys.path.insert(0, str(REPO / "scripts"))
    from reportlib import AQUA, BLUE, KEPT, MUTED, ORANGE, plt, save, style, tidy

    cells = load_runs()
    cols = {"duckdb": KEPT, "polars": BLUE, "postgres": AQUA, "spark": ORANGE}
    rows = []
    for (e, w, s), c in sorted(cells.items()):
        r0 = c["recs"][0]
        ref = cells.get(("duckdb", w, s))
        ok = bool(c["walls"])
        row = {
            "engine": e,
            "workload": w,
            "scale": s,
            "status": "ok" if ok else r0["status"],
            "reps": len(c["walls"]),
            "median_s": round(statistics.median(c["walls"]), 2) if ok else None,
            "min_s": round(min(c["walls"]), 2) if ok else None,
            "max_s": round(max(c["walls"]), 2) if ok else None,
            "peak_rss_mb": max(r["peak_rss_mb"] for r in c["recs"]),
            "spill_gb": round(max(r["spill_bytes"] for r in c["recs"]) / 1e9, 2),
            "out_gb": round(c["recs"][-1].get("out_bytes", 0) / 1e9, 3),
            "load_s": round(c["recs"][-1].get("load_s", 0) or 0, 1),
            "matches_duckdb": _same(c["recs"][-1].get("check"), ref["recs"][-1].get("check"))
            if ok and ref and ref["walls"]
            else None,
        }
        if not ok:
            row["stderr_tail"] = r0.get("stderr_tail", "")[-300:]
        rows.append(row)
    # lines changed by hand to port the SQL (sqlglot output vs the final text) and lines of Polars code
    import inspect

    port = {w: {e: sql_for(w, e)[1] for e in ("postgres", "spark")} for w in WORKLOADS}
    pl_lines = {
        "silver_contact_history": len(
            [x for x in inspect.getsource(polars_w1_exprs).splitlines() if x.strip()]
        ),
        "roll_rate": len([x for x in inspect.getsource(polars_w2).splitlines() if x.strip()]),
        "account_history": len([x for x in inspect.getsource(polars_w3).splitlines() if x.strip()]),
    }
    sql_lines = {w: len([x for x in sql_for(w, "duckdb")[0].splitlines() if x.strip()]) for w in WORKLOADS}
    for w in WORKLOADS:
        port[w]["polars"] = pl_lines[w]
        port[w]["duckdb"] = 0
        port[w]["sql_lines"] = sql_lines[w]
    # DuckDB growth: log-log slope between the largest measured scales, then the scale at which it would pass the thresholds
    import math

    ext = {}
    for w in WORKLOADS:
        pts = [
            (r["scale"], r["median_s"], r["spill_gb"])
            for r in rows
            if r["engine"] == "duckdb" and r["workload"] == w and r["median_s"]
        ]
        pts.sort()
        (s1, t1, _), (s2, t2, sp2) = pts[-2], pts[-1]
        k = math.log(t2 / t1) / math.log(s2 / s1)
        ext[w] = {
            "measured_to_scale": s2,
            "t_at_max_s": t2,
            "growth_exponent_last_step": round(k, 2),
            "spill_gb_at_max": sp2,
            "scale_for_1h": round(s2 * (3600 / t2) ** (1 / k), 0) if k > 0 else None,
            "scale_for_6h": round(s2 * (21600 / t2) ** (1 / k), 0) if k > 0 else None,
        }
    # working set of DuckDB under the 4 GB limit = limit + bytes spilled to disk (the spill dir is only clean for the two query workloads)
    ws = {}
    for w in ("roll_rate", "account_history"):
        pts = [
            (r["scale"], 4 + r["spill_gb"])
            for r in rows
            if r["engine"] == "duckdb" and r["workload"] == w and r["scale"] >= 10 and r["median_s"]
        ]
        slope = sum(x * y for x, y in pts) / sum(x * x for x, _ in pts)  # least squares through the origin
        ws[w] = {
            "points_scale_gb": pts,
            "gb_per_scale_unit": round(slope, 3),
            "scale_at_24gb_extrapolated": round(24 / slope, 1),
        }
    # Polars: peak RSS per scale unit at the largest scale that finished; scale at which 24 GB would be reached (extrapolated)
    pw = {}
    for w in WORKLOADS:
        pts = [
            (r["scale"], r["peak_rss_mb"] / 1000)
            for r in rows
            if r["engine"] == "polars" and r["workload"] == w and r["median_s"]
        ]
        if pts:
            s_, g_ = max(pts)
            pw[w] = {
                "largest_ok_scale": s_,
                "peak_gb": round(g_, 2),
                "scale_at_24gb_extrapolated": round(24 / (g_ / s_), 1),
            }
    out = {
        "duckdb_working_set": ws,
        "polars_memory": pw,
        "nightly_log_seconds": {"silver": 96, "features": 29, "score": 81, "total": 408},
        "skipped": [{"engine": k[0], "workload": k[1], "scale": k[2], "reason": v} for k, v in SKIPS.items()],
        "runs": rows,
        "lines_changed_by_hand": port,
        "duckdb_extrapolation": ext,
        "input_gb_1x": {t: round(dir_bytes(SCR / "base" / f"{t}.parquet") / 1e9, 3) for t in TABLES},
        "method": "median of 3 separate processes (Postgres: 3 runs in one process after one load); wall time of the job only, excluding start-up and, for Postgres, the load; peak RSS is the sum over the process tree sampled every 0.2 s (Postgres: container memory from docker stats)",
    }
    OUT.write_text(json.dumps(out, indent=1, default=str))
    style()
    fig, axes = plt.subplots(1, 3, figsize=(11, 3.6), sharey=False)
    names = {
        "silver_contact_history": "Silver contact_history build",
        "roll_rate": "roll_rate query",
        "account_history": "Account history features",
    }
    for ax, w in zip(axes, WORKLOADS, strict=True):
        ymin = min(r["median_s"] for r in rows if r["workload"] == w and r["median_s"]) * 0.7
        for e in ENGINES:
            pts = sorted(
                (r["scale"], r["median_s"])
                for r in rows
                if r["engine"] == e and r["workload"] == w and r["median_s"]
            )
            if pts:
                ax.plot(*zip(*pts, strict=True), "-o", color=cols[e], label=e, lw=1.6, ms=4)
            for r in rows:
                if r["engine"] == e and r["workload"] == w and not r["median_s"]:
                    ax.plot([r["scale"]], [ymin], "x", color=cols[e], ms=8)
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_title(names[w])
        ax.set_xlabel("scale (x the real data)")
        tidy(ax, "y")
        ax.set_xticks([1, 5, 10, 20, 40])
        ax.set_xticklabels(["1", "5", "10", "20", "40"])
    axes[0].set_ylabel("wall time, seconds (log)")
    axes[0].legend(frameon=False, fontsize=8)
    fig.text(0.99, 0.01, "x = killed or timed out inside the 8 GB cap", ha="right", color=MUTED, fontsize=7)
    print(save(fig, "dec_A1"))


if __name__ == "__main__":
    main()
