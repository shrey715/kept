"""Reader for contracts/c360_customer.odcs.yaml (Track A owns; B, C, D read).

Layers 2 and 3 take their allow-lists and permitted features straight from the
data contract (design, "Draft Data Contract"). Nobody hard-codes a column list.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from kept.config import DATA_CONTRACT_PATH
from kept.contracts.enums import Sensitivity


@dataclass(frozen=True, slots=True)
class ColumnSpec:
    table: str  # e.g. "gold.c360_customer"
    name: str
    logical_type: str
    sensitivity: Sensitivity
    required: bool
    description: str


@dataclass(frozen=True, slots=True)
class DataContract:
    version: str
    columns: tuple[ColumnSpec, ...]
    protected_attributes: frozenset[str]  # the 12 in the data dictionary
    proxy_attributes: frozenset[str]  # age, postal code, language, benefit flags, voice ...
    restricted_tables: frozenset[str]  # gold.c360_restricted
    ask_allowed_tables: frozenset[str]
    direct_pii_columns: frozenset[str] = frozenset()  # "table.column" in the source tables
    quasi_identifier_columns: frozenset[str] = frozenset()  # "table.column" in the source tables

    def table_columns(self, table: str) -> tuple[ColumnSpec, ...]:
        return tuple(c for c in self.columns if c.table == table)

    def columns_with(self, *sensitivity: Sensitivity) -> frozenset[str]:
        """Column names whose sensitivity is in `sensitivity`."""
        return frozenset(c.name for c in self.columns if c.sensitivity in sensitivity)

    def ask_blocked_columns(self) -> frozenset[str]:
        """Bare column names Ask must never touch: protected attributes, proxies, direct PII
        in gold, and every direct-PII column listed for the source tables."""
        source_pii = {ref.partition(".")[2] for ref in self.direct_pii_columns}
        return (
            self.protected_attributes
            | self.proxy_attributes
            | self.columns_with(Sensitivity.DIRECT_PII)
            | source_pii
        )


def _require(d: object, key: str, where: str) -> Any:
    if not isinstance(d, dict) or key not in d:
        raise ValueError(f"data contract: {where} is missing '{key}'")
    return d[key]


def load_data_contract(path: Path = DATA_CONTRACT_PATH) -> DataContract:
    """Parse the ODCS YAML. Raise ValueError on anything malformed (CI lints it)."""
    try:
        doc = yaml.safe_load(Path(path).read_text())
    except yaml.YAMLError as e:
        raise ValueError(f"data contract: {path} is not valid YAML: {e}") from e

    columns: list[ColumnSpec] = []
    for table in _require(doc, "schema", "contract"):
        physical = _require(table, "physicalName", "a schema table")
        for prop in _require(table, "properties", physical):
            name = _require(prop, "name", physical)
            try:
                sensitivity = Sensitivity(_require(prop, "classification", f"{physical}.{name}"))
            except ValueError:
                raise ValueError(
                    f"data contract: {physical}.{name} has unknown classification {prop['classification']!r}"
                ) from None
            columns.append(
                ColumnSpec(
                    table=physical,
                    name=name,
                    logical_type=_require(prop, "logicalType", f"{physical}.{name}"),
                    sensitivity=sensitivity,
                    required=bool(prop.get("required", False)),
                    description=prop.get("description", ""),
                )
            )

    custom = {p["property"]: p["value"] for p in _require(doc, "customProperties", "contract")}

    def listed(key: str, *, optional: bool = False) -> frozenset[str]:
        if key not in custom and optional:
            return frozenset()
        return frozenset(_require(custom, key, "customProperties"))

    return DataContract(
        version=str(_require(doc, "version", "contract")),
        columns=tuple(columns),
        protected_attributes=listed("protectedAttributes"),
        proxy_attributes=listed("proxyAttributes"),
        restricted_tables=listed("restrictedTables"),
        ask_allowed_tables=listed("askAllowedTables"),
        direct_pii_columns=listed("directPiiColumns", optional=True),
        quasi_identifier_columns=listed("quasiIdentifierColumns", optional=True),
    )
