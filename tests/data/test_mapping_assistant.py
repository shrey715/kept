"""draft_mapping: the LLM sees only the schema, and cannot map to a column that does not exist."""

from __future__ import annotations

import json

import pytest

from kept.data.mapping_assistant import PURPOSE, draft_mapping
from tests.fakes import PassThroughRedactor, ScriptedLLM

SOURCE = {"cust_ref": "VARCHAR", "dob_keyed": "VARCHAR", "phone_txt": "VARCHAR", "stmt_dt": "DATE"}
TARGET = ["crm_customer_id", "date_of_birth", "primary_phone_raw", "email"]


def _reply(column_map: dict[str, str | None]) -> dict[str, object]:
    return {"column_map": column_map, "rationale": "names match"}


def test_draft_maps_what_exists_and_lists_the_rest() -> None:
    llm = ScriptedLLM(
        [
            _reply(
                {
                    "crm_customer_id": "cust_ref",
                    "date_of_birth": "dob_keyed",
                    "primary_phone_raw": "phone_txt",
                    "email": None,
                }
            )
        ]
    )
    d = draft_mapping("crm_feed", SOURCE, "customers", TARGET, llm=llm, redactor=PassThroughRedactor())
    assert d.column_map == {
        "crm_customer_id": "cust_ref",
        "date_of_birth": "dob_keyed",
        "primary_phone_raw": "phone_txt",
    }
    assert d.unmapped == ("email",) and d.rationale == "names match"
    assert (
        'select\n    "cust_ref" as "crm_customer_id"' in d.sql() and "source('bronze', 'crm_feed')" in d.sql()
    )


def test_only_names_and_types_are_sent_to_the_llm() -> None:
    llm = ScriptedLLM([_reply({t: None for t in TARGET})])
    draft_mapping("crm_feed", SOURCE, "customers", TARGET, llm=llm, redactor=PassThroughRedactor())
    (call,) = llm.calls
    assert call["purpose"] == PURPOSE
    sent = json.loads(call["user"].text)
    assert sent == {"source_columns": SOURCE, "target_columns": TARGET}  # no rows, no values


def test_a_column_the_llm_invented_is_rejected() -> None:
    llm = ScriptedLLM(
        [_reply({"crm_customer_id": "customer_number", "email": None})]
    )  # no such source column
    with pytest.raises(ValueError, match="customer_number"):
        draft_mapping("crm_feed", SOURCE, "customers", TARGET, llm=llm, redactor=PassThroughRedactor())


def test_schema_drift_finds_new_and_missing_columns(tmp_path) -> None:  # type: ignore[no-untyped-def]
    import duckdb

    from kept.data.mapping_assistant import Drift, raw_columns, schema_drift

    (tmp_path / "contacts.csv").write_text("contact_id,channel,channel_v2\n1,call,\n")
    part = tmp_path / "snapshots" / "year=2026"
    part.mkdir(parents=True)
    duckdb.connect().execute(
        f"copy (select 1 as account_id, 2 as dpd) to '{part / 'p.parquet'}' (format parquet)"
    )
    expected = {"contacts": ["contact_id", "channel"], "snapshots": ["account_id", "dpd", "month_end_date"]}
    got = schema_drift(expected, raw_columns(tmp_path, ["contacts", "snapshots", "absent"]))
    assert got == [
        Drift("contacts", {"channel_v2": "VARCHAR"}, ()),
        Drift("snapshots", {}, ("month_end_date",)),  # the year=2026 partition key is not a column
    ]
