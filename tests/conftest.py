"""Shared fixtures, track markers, and the --allow-stubs switch.

TDD workflow:
  * `uv run pytest tests/<your layer>` is red until you implement; make it green.
  * `uv run pytest --allow-stubs` reports tests that hit a NotImplementedError stub
    (or are marked `todo`) as xfail, so CI stays green while showing progress.
    Real failures still fail.
  * Run one track: `uv run pytest -m track_b`.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
import yaml

from kept.config import DATA_CONTRACT_PATH, REPO_ROOT
from kept.contracts import (
    CaseContext,
    ContactPermissions,
    DpdBucket,
    GoldenCustomer,
    HardshipStatus,
    MatchReviewStatus,
    PayrollFrequency,
    SourceKey,
    SourceSystem,
)

from .fakes import InMemoryAuditLog, PassThroughRedactor, ScriptedLLM

# --------------------------------------------------------------------- markers
_DIR_MARKERS = {
    "contracts": "contract",
    "data": "track_a",
    "ask": "track_b",
    "text": "track_c",
    "hardship": "track_c",
    "governance": "track_c",
    "features": "track_d",
    "nba": "track_d",
    "app": "track_d",
    "common": "track_d",
}
_TRACK_MARKERS = {"track_a", "track_b", "track_c", "track_d", "contract"}


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--allow-stubs",
        action="store_true",
        default=False,
        help="Report tests that hit an unimplemented stub as xfail instead of failed.",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    tests_root = Path(__file__).parent
    for item in items:
        if any(m.name in _TRACK_MARKERS for m in item.iter_markers()):
            continue  # file-level pytestmark overrides the directory default
        rel = Path(str(item.fspath)).relative_to(tests_root)
        marker = _DIR_MARKERS.get(rel.parts[0]) if len(rel.parts) > 1 else None
        if marker:
            item.add_marker(getattr(pytest.mark, marker))


def _is_stub(exc: BaseException | None) -> bool:
    seen: set[int] = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, NotImplementedError):
            return True
        if isinstance(exc, BaseExceptionGroup):
            return all(_is_stub(e) for e in exc.exceptions)
        exc = exc.__cause__ or exc.__context__
    return False


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[Any]):  # type: ignore[no-untyped-def]
    outcome = yield
    report = outcome.get_result()
    if item.config.getoption("--allow-stubs") and call.excinfo is not None and report.failed:
        if _is_stub(call.excinfo.value):
            report.outcome = "skipped"
            report.wasxfail = f"stub: {call.excinfo.value}"
        elif (todo := item.get_closest_marker("todo")) is not None:
            report.outcome = "skipped"
            report.wasxfail = f"todo: {todo.args[0] if todo.args else item.name}"


# --------------------------------------------------------------------- time
@pytest.fixture
def toronto() -> ZoneInfo:
    return ZoneInfo("America/Toronto")


@pytest.fixture
def now_utc() -> datetime:
    # Fri 2 Oct 2026, 22:00 UTC = 18:00 Toronto (EDT): inside calling hours.
    return datetime(2026, 10, 2, 22, 0, tzinfo=UTC)


# --------------------------------------------------------------------- contract
@pytest.fixture(scope="session")
def contract_path() -> Path:
    return DATA_CONTRACT_PATH


@pytest.fixture(scope="session")
def contract_yaml(contract_path: Path) -> dict[str, Any]:
    with contract_path.open() as fh:
        return yaml.safe_load(fh)


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


# --------------------------------------------------------------------- factories
@pytest.fixture
def make_customer(now_utc: datetime) -> Callable[..., GoldenCustomer]:
    def _make(**overrides: Any) -> GoldenCustomer:
        base: dict[str, Any] = {
            "golden_customer_id": "G-004817",
            "source_keys": (
                SourceKey(system=SourceSystem.CRM, key="CRM-1"),
                SourceKey(system=SourceSystem.CARD, key="CARD-9"),
            ),
            "match_confidence_min": 0.97,
            "match_review_status": MatchReviewStatus.AUTO,
            "display_name": "Jane Doe",
            "primary_phone_e164": "+14165550123",
            "email": "jane.doe@example.com",
            "province_code": "ON",
            "time_zone": "America/Toronto",
            "preferred_language": "en",
            "total_overdue": Decimal("420.00"),
            "max_dpd": 18,
            "current_bucket": DpdBucket.B1_30,
            "open_case_id": "C-118204",
            "assigned_agent_id": "agent-7",
            "contact_permissions": ContactPermissions(call=True, sms=True, email=True, push=False),
            "do_not_contact": False,
            "collections_hold": False,
            "hardship_status": HardshipStatus.NONE,
            "expected_next_payroll_date": date(2026, 10, 2),
            "payroll_frequency_detected": PayrollFrequency.MONTHLY,
            "as_of_date": date(2026, 9, 28),
            "refreshed_at": datetime(2026, 9, 28, 10, 0, tzinfo=UTC),
        }
        base.update(overrides)
        return GoldenCustomer(**base)

    return _make


@pytest.fixture
def make_ctx(now_utc: datetime) -> Callable[..., CaseContext]:
    def _make(**overrides: Any) -> CaseContext:
        base: dict[str, Any] = {
            "case_id": "C-118204",
            "golden_customer_id": "G-004817",
            "assigned_agent_id": "agent-7",
            "now": now_utc,
            "time_zone": "America/Toronto",
            "contact_permissions": ContactPermissions(call=True, sms=True, email=True, push=True),
            "do_not_contact": False,
            "contacts_last_7d": 2,
            "hardship_status": HardshipStatus.NONE,
            "balance_at_risk": Decimal("420.00"),
            "expected_next_payroll_date": date(2026, 10, 2),
            "payroll_frequency": PayrollFrequency.MONTHLY,
            "estimated_monthly_spare_cash": Decimal("160.00"),
            "features_as_of": now_utc - timedelta(hours=16),
        }
        base.update(overrides)
        return CaseContext(**base)

    return _make


# --------------------------------------------------------------------- fakes
@pytest.fixture
def audit_log() -> InMemoryAuditLog:
    return InMemoryAuditLog()


@pytest.fixture
def scripted_llm() -> ScriptedLLM:
    return ScriptedLLM()


@pytest.fixture
def redactor() -> PassThroughRedactor:
    return PassThroughRedactor()
