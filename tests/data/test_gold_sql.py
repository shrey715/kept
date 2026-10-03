"""The gold SQL repeats the flag lists of kept.data.gold (SQL cannot import them): keep them in step."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from kept.data.gold import (
    COLLECTIONS_HOLD_STOPS,
    DO_NOT_CONTACT_FLAGS,
    GOLD_MODELS,
    HARD_STOP_FLAGS,
)

MODELS = Path(__file__).resolve().parents[2] / "dbt" / "models"


def _flag_map() -> dict[str, tuple[str | None, bool, bool]]:
    """flag -> (stop, is_do_not_contact, is_collections_hold) from the VALUES list in int_source_flags."""
    sql = (MODELS / "silver" / "int_source_flags.sql").read_text()
    rows = re.findall(r"\('(\w+)', (null|'\w+'), (true|false), (true|false)\)", sql)
    return {f: (None if s == "null" else s.strip("'"), d == "true", h == "true") for f, s, d, h in rows}


def test_every_source_flag_is_collected_by_int_flag_events() -> None:
    sql = (MODELS / "silver" / "int_flag_events.sql").read_text()
    wanted = set(DO_NOT_CONTACT_FLAGS) | {f for flags in HARD_STOP_FLAGS.values() for f in flags}
    assert wanted == set(re.findall(r"'(\w+_(?:flag|indicator))'", sql))


def test_national_dncl_never_reaches_the_gold_sql() -> None:
    for name in ("int_flag_events", "int_source_flags"):
        # the comment may name it; the flag must never be a value in the SQL
        assert "'national_dncl_flag'" not in (MODELS / "silver" / f"{name}.sql").read_text()


def test_flag_map_matches_gold_py() -> None:
    flag_map = _flag_map()
    for flag in DO_NOT_CONTACT_FLAGS:
        assert flag_map[flag][1], flag
    for stop, flags in HARD_STOP_FLAGS.items():
        for flag in flags:
            assert flag_map[flag][0] == stop.value, flag
            assert flag_map[flag][2] == (stop in COLLECTIONS_HOLD_STOPS), flag
    # a flag only counts as a hold when its stop does; internal do-not-call is no hard stop
    assert flag_map["internal_do_not_call_flag"] == (None, True, False)
    assert set(flag_map) == set(DO_NOT_CONTACT_FLAGS) | {f for fs in HARD_STOP_FLAGS.values() for f in fs}


@pytest.mark.parametrize("model", GOLD_MODELS)
def test_gold_build_list_names_real_models(model: str) -> None:
    if model == "cashflow_observations" and not list(MODELS.rglob(f"{model}.sql")):
        pytest.skip("Track C's model arrives with their PR #25 (merged before this one); drop this skip then")
    assert list(MODELS.rglob(f"{model}.sql")), model
