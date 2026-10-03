"""C360Reader over the warehouse: gold.c360_customer + gold.identity_crosswalk (Track A).

Opens a read-only connection per call and closes it (K5: DuckDB allows one writer, and the
nightly build must be able to take the file between requests).
"""

from __future__ import annotations

from pathlib import Path

from kept.common.db import connect
from kept.config import WAREHOUSE_PATH
from kept.contracts.enums import HardStop
from kept.contracts.identity import ContactPermissions, GoldenCustomer, SourceKey


class DuckDBC360Reader:
    def __init__(self, path: Path | str = WAREHOUSE_PATH) -> None:
        self._path = path

    def _query(self, sql: str, params: list[str]) -> list[dict[str, object]]:
        conn = connect(self._path, read_only=True)
        try:
            cursor = conn.execute(sql, params)
            names = [d[0] for d in cursor.description]
            return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_customer(self, golden_customer_id: str) -> GoldenCustomer:
        """Raise KeyError if unknown."""
        rows = self._query(
            "select * from gold.c360_customer where golden_customer_id = ?", [golden_customer_id]
        )
        if not rows:
            raise KeyError(golden_customer_id)
        return _to_customer(rows[0])

    def resolve(self, key: SourceKey) -> str | None:
        """Golden ID for a source key, or None if the key is unknown."""
        rows = self._query(
            "select golden_customer_id from gold.identity_crosswalk "
            "where source_system = ? and source_key = ? and valid_to is null",
            [key.system.value, key.key],
        )
        return str(rows[0]["golden_customer_id"]) if rows else None

    def customer_for_case(self, case_id: str) -> GoldenCustomer:
        """Every open case resolves to a golden ID (quality rule 2). Raise KeyError if not."""
        # through the case's own customer key, so a second open case of one customer resolves too
        rows = self._query(
            "select x.golden_customer_id from silver.collections_cases c "
            "join gold.identity_crosswalk x on x.source_system = 'collections' "
            "and x.source_key = c.coll_customer_ref and x.valid_to is null where c.case_id = ?",
            [case_id],
        )
        if not rows:
            raise KeyError(case_id)
        return self.get_customer(str(rows[0]["golden_customer_id"]))


def _to_customer(row: dict[str, object]) -> GoldenCustomer:
    data = dict(row)
    data["source_keys"] = tuple(
        SourceKey(system=system, key=key)  # type: ignore[arg-type]
        for system, _, key in (str(k).partition(":") for k in data["source_keys"])  # type: ignore[attr-defined]
    )
    data["contact_permissions"] = ContactPermissions(**data["contact_permissions"])  # type: ignore[arg-type]
    data["hard_stop_flags"] = frozenset(HardStop(s) for s in data["hard_stop_flags"] or ())  # type: ignore[attr-defined]
    return GoldenCustomer(**data)  # type: ignore[arg-type]
