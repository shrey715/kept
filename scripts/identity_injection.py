# ruff: noqa: E501  (report prose)
"""Identity recall by injection: plant known duplicates, check they merge with their original, and that nothing
else moves. docs/reports/identity_recall.md.

    uv run python scripts/identity_injection.py [--warehouse copy.duckdb] [--sample-mod 20] [--per-kind 40]

Precision is checked by hand (300 links, quality report). Recall can't be measured against the CRM's own duplicate
pointer (duplicate_of_crm_id), because the matcher uses that pointer as an exact rule. So this plants new CRM
records copied from real customers, with no national ID and no duplicate pointer (only the probabilistic matcher
can find them), each damaged one way, and runs the matcher twice on the same DOB-hash sample: without and with
them. Read-only on the warehouse.
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

import duckdb
import pandas as pd

from kept.config import WAREHOUSE_PATH
from kept.data.identity.pipeline import run_matching

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "docs" / "reports" / "identity_recall.md"
KINDS = {
    "exact copy": lambda r, g: r,
    "surname typo": lambda r, g: {**r, "name_key": _typo(r["name_key"], g)},
    "no phone": lambda r, g: {**r, "phone_e164": None},
    "moved (new postal code)": lambda r, g: {**r, "postal_code": _postal(g)},
    "first initial only": lambda r, g: {**r, "first_name_key": (r["first_name_key"] or "x")[0]},
}


def _typo(name: str, g: random.Random) -> str:
    i = g.randrange(1, max(2, len(name) - 1))  # swap two neighbouring letters, never the initial
    return name[:i] + name[i + 1 : i + 2] + name[i : i + 1] + name[i + 2 :] if len(name) > 3 else name + "e"


def _postal(g: random.Random) -> str:
    a = "ABCEGHJKLMNPRSTVXY"
    return f"{g.choice(a)}{g.randrange(10)}{g.choice(a)} {g.randrange(10)}{g.choice(a)}{g.randrange(10)}"


def partition(crosswalk: pd.DataFrame) -> set[frozenset[str]]:
    """Clusters as sets of source keys: golden IDs themselves may be renumbered between runs."""
    keys = crosswalk.source_system + ":" + crosswalk.source_key
    return {frozenset(s) for _, s in keys.groupby(crosswalk.golden_customer_id)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--warehouse", default=str(WAREHOUSE_PATH))
    ap.add_argument("--sample-mod", type=int, default=20)
    ap.add_argument("--per-kind", type=int, default=40)
    a = ap.parse_args()
    g = random.Random(0)
    src = duckdb.connect(a.warehouse, read_only=True)
    sample = f"dob is not null and hash(dob) % {a.sample_mod} = 0"
    records = src.execute(f"select * from silver.int_identity_records where {sample}").df()
    evidence = src.execute("select * from silver.int_identity_evidence").df()
    src.close()
    crm = records[
        (records.source_system == "crm") & records.name_key.notna() & records.first_name_key.notna()
    ]
    originals = crm.sample(len(KINDS) * a.per_kind, random_state=0).to_dict("records")
    planted = []
    for i, r in enumerate(originals):
        kind = list(KINDS)[i % len(KINDS)]
        new = KINDS[kind](dict(r), g) | {"source_key": f"INJ-{i:04d}", "national_id_hash": None}
        planted.append({"kind": kind, "original": r["source_key"], "key": new["source_key"], "row": new})

    def run(extra: list[dict]) -> pd.DataFrame:  # type: ignore[type-arg]
        con = duckdb.connect()
        con.execute("create schema silver")
        recs = (
            pd.concat([records, pd.DataFrame([p["row"] for p in extra])], ignore_index=True)
            if extra
            else records
        )
        ev_new = pd.DataFrame(
            [
                {c: None for c in evidence.columns} | {"source_system": "crm", "source_key": p["key"]}
                for p in extra
            ]
        )
        evs = pd.concat([evidence, ev_new], ignore_index=True) if extra else evidence
        con.register("r", recs)
        con.register("e", evs)
        con.execute("create table silver.int_identity_records as select * from r")
        con.execute("create table silver.int_identity_evidence as select * from e")
        return run_matching(
            con, sample_mod=a.sample_mod, train_sample_mod=1, verdicts=pd.DataFrame()
        ).crosswalk

    base, injected = run([]), run(planted)
    golden = dict(
        zip(injected.source_system + ":" + injected.source_key, injected.golden_customer_id, strict=True)
    )
    found = pd.DataFrame(
        [
            {"kind": p["kind"], "merged": golden.get("crm:" + p["key"]) == golden.get("crm:" + p["original"])}
            for p in planted
        ]
    )
    stripped = {frozenset(k for k in c if not k.startswith("crm:INJ-")) for c in partition(injected)} - {
        frozenset()
    }
    moved = len(partition(base) - stripped)  # clusters of the clean run that no longer exist as they were
    size = injected.groupby("golden_customer_id").size()
    missed = [p for p, ok in zip(planted, found.merged, strict=True) if not ok]
    wrong = sum(size[golden["crm:" + p["key"]]] > 1 for p in missed)  # a miss that joined someone else
    rows = "\n".join(
        f"| {k} | {int(g_.merged.sum())} of {len(g_)} | {100 * g_.merged.mean():.0f}% |"
        for k, g_ in found.groupby("kind", sort=False)
    )
    OUT.write_text(f"""# Identity: recall by injection

Generated by `scripts/identity_injection.py`. Precision is checked by hand: **99.3%** on 300 reviewed links (quality
report). Recall needs people we *know* should merge. The CRM's own duplicate pointer can't serve: the matcher uses it
as an exact rule. So we planted {len(planted)} new CRM records, each a copy of a real customer with **no national ID
and no duplicate pointer** (only the probabilistic matcher can find them), damaged one way, and ran the matcher on
the same {100 // a.sample_mod}% sample of people (by date of birth) with and without them.

| Planted duplicate | Merged with the original | Recall |
|---|---:|---:|
{rows}
| **All** | **{int(found.merged.sum())} of {len(found)}** | **{100 * found.merged.mean():.0f}%** |

**Missed:** {len(missed)}, of which {wrong} joined somebody else; the rest stayed a person of their own, which a
steward can join (a missed link, not a wrong one).

**Nothing else moved, almost:** with the planted records taken back out, {moved} of the clean run's
{len(partition(base)):,} clusters aren't exactly as they were. The matcher is retrained on each run's records (its
weights come from the data), so a borderline pair can land the other side of the threshold.
""")
    print(
        f"wrote {OUT}: recall {100 * found.merged.mean():.0f}%, {wrong} wrong merges, {moved} other clusters moved"
    )


if __name__ == "__main__":
    main()
