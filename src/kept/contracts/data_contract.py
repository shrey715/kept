"""Reader for contracts/c360_customer.odcs.yaml (Track A owns; B, C, D read).

Layers 2 and 3 take their allow-lists and permitted features straight from the
data contract (design, "Draft Data Contract"). Nobody hard-codes a column list.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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
        raise NotImplementedError("Track A")

    def columns_with(self, *sensitivity: Sensitivity) -> frozenset[str]:
        """Column names whose sensitivity is in `sensitivity`."""
        raise NotImplementedError("Track A")

    def ask_blocked_columns(self) -> frozenset[str]:
        """Bare column names Ask must never touch: protected attributes, proxies, direct PII
        in gold, and every direct-PII column listed for the source tables."""
        raise NotImplementedError("Track A")


def load_data_contract(path: Path = DATA_CONTRACT_PATH) -> DataContract:
    """Parse the ODCS YAML. Raise ValueError on anything malformed (CI lints it)."""
    raise NotImplementedError("Track A: hour 0-3 'Load tables, contract'")
