"""The shared models enforce their own invariants. These must always be green."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import TypeAdapter, ValidationError

from kept.contracts import (
    ACTION_CHANNEL,
    HARDSHIP_ALLOWED_ACTIONS,
    Action,
    AskAnswer,
    AskResponse,
    Channel,
    Clarification,
    FeatureVector,
    HardStop,
    HardStopResult,
    Intent,
    IntentKind,
    NBACard,
    PermissionResult,
    PromiseSizing,
    Proposal,
    Reason,
    RedactedText,
    Refusal,
    RefusalReason,
    ReleaseDecision,
    ReleaseTier,
    ReviewDecision,
    Role,
)
from kept.contracts.nba import CheckName, CheckResult

T0 = datetime(2026, 10, 2, 22, 0, tzinfo=UTC)


# ----------------------------------------------------------------- enums
def test_there_are_exactly_eight_actions() -> None:
    assert {a.value for a in Action} == {
        "wait",
        "email",
        "push",
        "sms_payment_link",
        "call",
        "promise_request",
        "payment_plan",
        "hardship_review",
    }


def test_every_action_has_a_channel_entry_and_only_wait_has_none() -> None:
    assert set(ACTION_CHANNEL) == set(Action)
    assert [a for a, c in ACTION_CHANNEL.items() if c is None] == [Action.WAIT]
    assert ACTION_CHANNEL[Action.SMS_PAYMENT_LINK] is Channel.SMS


def test_action_channel_is_read_only() -> None:
    with pytest.raises(TypeError):
        ACTION_CHANNEL[Action.WAIT] = Channel.CALL  # type: ignore[index]


def test_hardship_allowed_actions_are_protective_only() -> None:
    assert {
        Action.CALL,
        Action.HARDSHIP_REVIEW,
        Action.PAYMENT_PLAN,
        Action.WAIT,
    } == HARDSHIP_ALLOWED_ACTIONS
    # The design explicitly removes SMS links under hardship.
    assert Action.SMS_PAYMENT_LINK not in HARDSHIP_ALLOWED_ACTIONS


def test_release_tier_declaration_order_is_precedence() -> None:
    assert list(ReleaseTier) == [ReleaseTier.BLOCKED, ReleaseTier.RED, ReleaseTier.AMBER, ReleaseTier.GREEN]


# ----------------------------------------------------------------- identity
@pytest.mark.parametrize("bad_id", ["", "G-1", "g-004817", "C-004817", "G-00481X", "004817"])
def test_golden_id_format_is_enforced(make_customer, bad_id: str) -> None:
    with pytest.raises(ValidationError):
        make_customer(golden_customer_id=bad_id)


def test_golden_customer_rejects_naive_refreshed_at(make_customer) -> None:
    with pytest.raises(ValidationError):
        make_customer(refreshed_at=datetime(2026, 9, 28, 10, 0))


@pytest.mark.parametrize(
    "field,value",
    [
        ("total_overdue", Decimal("-0.01")),
        ("max_dpd", -1),
        ("match_confidence_min", 1.01),
        ("primary_phone_e164", "4165550123"),
        ("province_code", "Ontario"),
        ("source_keys", ()),
    ],
)
def test_golden_customer_field_constraints(make_customer, field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        make_customer(**{field: value})


def test_golden_customer_is_frozen_and_forbids_extra(make_customer) -> None:
    c = make_customer()
    with pytest.raises(ValidationError):
        c.max_dpd = 99  # type: ignore[misc]
    with pytest.raises(ValidationError):
        make_customer(gender_code="F")  # protected attributes can never ride along


def test_golden_customer_json_round_trip(make_customer) -> None:
    c = make_customer()
    assert type(c).model_validate_json(c.model_dump_json()) == c


# ----------------------------------------------------------------- features
def test_feature_vector_requires_aware_as_of() -> None:
    with pytest.raises(ValidationError):
        FeatureVector(
            case_id="C-1", golden_customer_id="G-000001", as_of=datetime(2026, 1, 1), feature_set_version="v"
        )


def test_feature_vector_missing_stays_missing() -> None:
    fv = FeatureVector(case_id="C-1", golden_customer_id="G-000001", as_of=T0, feature_set_version="v")
    assert all(getattr(fv, n) is None for n in FeatureVector.feature_names())


def test_feature_vector_has_no_stated_reason_or_outcome() -> None:
    names = set(FeatureVector.model_fields)
    assert "stated_reason" not in names
    assert not names & {"paid_14d", "dpd_at_day_30", "test_cell", "nba_recommendation_last"}


def test_redacted_text_requires_redactor_version() -> None:
    with pytest.raises(ValidationError):
        RedactedText(text="hello")  # type: ignore[call-arg]


# ----------------------------------------------------------------- nba
def test_hard_stop_result_blocked_iff_rules_fired() -> None:
    HardStopResult(blocked=False)
    HardStopResult(blocked=True, fired=(HardStop.CEASE,), rule_card="Cease request on file")
    with pytest.raises(ValidationError):
        HardStopResult(blocked=True)
    with pytest.raises(ValidationError):
        HardStopResult(blocked=False, fired=(HardStop.DECEASED,))


def test_permission_result_allowed_iff_all_checks_pass() -> None:
    ok = CheckResult(check=CheckName.CONSENT, passed=True, detail="call consent")
    bad = CheckResult(check=CheckName.CONTACT_CAP, passed=False, detail="3 of 3")
    PermissionResult(action=Action.CALL, allowed=True, checks=(ok,))
    with pytest.raises(ValidationError):
        PermissionResult(action=Action.CALL, allowed=True, checks=(ok, bad))
    with pytest.raises(ValidationError):
        PermissionResult(action=Action.CALL, allowed=False, checks=(ok,))


def _sizing(**kw: object) -> PromiseSizing:
    base: dict[str, object] = dict(
        amount=Decimal("140.00"),
        due_date=date(2026, 10, 3),
        installments=3,
        spare_cash_estimate=Decimal("160.00"),
        payday=date(2026, 10, 2),
        rationale="r",
    )
    base.update(kw)
    return PromiseSizing(**base)  # type: ignore[arg-type]


def test_promise_sizing_never_exceeds_spare_cash() -> None:
    _sizing(amount=Decimal("160.00"))
    with pytest.raises(ValidationError):
        _sizing(amount=Decimal("160.01"))


@pytest.mark.parametrize("kw", [{"amount": Decimal("0")}, {"installments": 0}, {"amount": Decimal("1.001")}])
def test_promise_sizing_constraints(kw: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _sizing(**kw)


def _proposal(**kw: object) -> Proposal:
    base: dict[str, object] = dict(
        proposal_id="P-1",
        case_id="C-1",
        golden_customer_id="G-000001",
        action=Action.CALL,
        channel=Channel.CALL,
        tier=ReleaseTier.AMBER,
        model_version="nba-0.3",
        features_as_of=T0 - timedelta(hours=16),
        created_at=T0,
        expires_at=T0 + timedelta(hours=4),
    )
    base.update(kw)
    return Proposal(**base)  # type: ignore[arg-type]


def test_proposal_time_ordering() -> None:
    _proposal()
    with pytest.raises(ValidationError):
        _proposal(expires_at=T0)
    with pytest.raises(ValidationError):
        _proposal(window_start=T0)  # without window_end
    with pytest.raises(ValidationError):
        _proposal(window_start=T0, window_end=T0 - timedelta(minutes=1))
    with pytest.raises(ValidationError):
        _proposal(created_at=datetime(2026, 10, 2, 22, 0))


def test_card_holds_at_most_three_reasons() -> None:
    r = Reason(feature="f", sentence="s", contribution_pts=1.0)
    kw = dict(
        case_id="C-1",
        golden_customer_id="G-000001",
        model_version="m",
        features_as_of=T0,
        headline="h",
        proposal=None,
        probabilities=(),
    )
    NBACard(**kw, reasons=(r, r, r))  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        NBACard(**kw, reasons=(r, r, r, r))  # type: ignore[arg-type]


def _decision(**kw: object) -> ReleaseDecision:
    base: dict[str, object] = dict(
        proposal_id="P-1",
        reviewer_id="u1",
        reviewer_role=Role.AGENT,
        decision=ReviewDecision.ACCEPT,
        decided_at=T0,
    )
    base.update(kw)
    return ReleaseDecision(**base)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "kw",
    [
        {"decision": ReviewDecision.OVERRIDE},
        {"decision": ReviewDecision.OVERRIDE, "override_reason": "   "},
        {"decision": ReviewDecision.ALTERNATIVE},
        {"decision": ReviewDecision.EDIT},
        {"second_reviewer_id": "u1"},
        {"decided_at": datetime(2026, 10, 2, 22, 0)},
    ],
)
def test_release_decision_shape_rules(kw: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _decision(**kw)


def test_release_decision_valid_shapes() -> None:
    _decision(decision=ReviewDecision.OVERRIDE, override_reason="customer asked for email")
    _decision(decision=ReviewDecision.ALTERNATIVE, alternative_action=Action.HARDSHIP_REVIEW)
    _decision(decision=ReviewDecision.EDIT, edited_amount=Decimal("120.00"))
    _decision(second_reviewer_id="u2", second_reviewer_role=Role.TEAM_LEAD)


# ----------------------------------------------------------------- ask
def test_ask_response_union_discriminates_on_kind() -> None:
    ta = TypeAdapter(AskResponse)
    intent = Intent(kind=IntentKind.METRIC, metric_id="roll_rate_30d", confidence=0.9)
    for obj in (
        AskAnswer(
            question="q",
            intent=intent,
            sql="SELECT 1",
            tables_used=("gold.x",),
            data_freshness=T0,
            narrative="n",
        ),
        Refusal(reason=RefusalReason.PROTECTED_ATTRIBUTE, message="m", suggestion="Try: x"),
        Clarification(question="Which month?"),
    ):
        back = ta.validate_json(ta.dump_json(obj))
        assert type(back) is type(obj)
        assert back == obj


def test_intent_confidence_is_a_probability() -> None:
    with pytest.raises(ValidationError):
        Intent(kind=IntentKind.LOOKUP, confidence=1.5)
