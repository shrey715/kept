"""LLM-written briefs that can't make things up: a case brief for the agent and a daily portfolio brief.

The model only sees numbered sources (facts computed by Kept, or quotes extracted from redacted notes and
calls) and must cite them. A bullet that cites nothing, cites a source that doesn't exist, or states a number
its sources lack is dropped before anyone sees it (kept.ask.grounding, the Ask's own check). If nothing
survives, a template brief stands in. Runs on the local model: the case's words never leave the machine.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel

from kept.ask.grounding import ungrounded_numbers
from kept.common.llm import Purpose
from kept.contracts.interfaces import LLMGateway
from kept.text.redact import fixed_text

Kind = Literal["fact", "quote"]


class Source(BaseModel):
    id: str  # F1, E2: what the bullets cite
    kind: Kind
    label: str  # "Recommended action", "Note N-102 · hardship"
    text: str


class Bullet(BaseModel):
    text: str
    cites: list[str]


class Brief(BaseModel):
    bullets: list[Bullet]
    sources: list[Source]
    model: str | None  # None: the template stood in
    dropped: int  # bullets the checks removed
    generated_at: datetime


_SCHEMA = {
    "type": "object",
    "properties": {
        "bullets": {
            "type": "array",
            "minItems": 1,
            "maxItems": 4,
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "cites": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["text", "cites"],
            },
        }
    },
    "required": ["bullets"],
}
_CITE = re.compile(r"\s*\[(?:[FE]\d+(?:,\s*)?)+\]")

CASE_SYSTEM = """You brief a collections agent before they act on one case. You get numbered sources:
F = facts Kept computed, E = the customer's own words, quoted from redacted notes and calls.
Write 3 short bullets (one sentence each): 1) the situation, 2) what the customer said, 3) what to do and
why. Every bullet lists the source ids it rests on in "cites". Use only facts in the sources: no number that
isn't in a cited source, no guesses about the customer. Plain, respectful English. Reply with JSON only."""

PORTFOLIO_SYSTEM = """You brief a collections team lead on tonight's portfolio. You get numbered facts (F)
that Kept computed from the warehouse. Write 3 short bullets (one sentence each): what stands out, what it
means for today, and what to watch. Every bullet lists the fact ids it rests on in "cites". Use only numbers
that appear in a cited fact, written the same way. Reply with JSON only."""


def check(bullets: Sequence[dict[str, Any]], sources: Sequence[Source]) -> tuple[list[Bullet], int]:
    """Keep a bullet only if it cites real sources and every number in it is in what it cites."""
    by_id = {s.id: s for s in sources}
    kept: list[Bullet] = []
    for b in bullets:
        cites = [c for c in dict.fromkeys(str(x).strip("[] ") for x in b.get("cites") or []) if c in by_id]
        text = _CITE.sub("", str(b.get("text", ""))).strip()
        if not text or not cites:
            continue
        rows = [[by_id[c].text] for c in cites]
        if ungrounded_numbers(text, rows):
            continue
        kept.append(Bullet(text=text, cites=cites))
    return kept, len(bullets) - len(kept)


def write(
    llm: LLMGateway | None,
    *,
    system: str,
    sources: Sequence[Source],
    fallback: Sequence[Bullet],
    purpose: str,
    actor_id: str,
) -> Brief:
    """Ask the model for cited bullets over `sources`; keep the ones that pass `check`, else the fallback."""
    now = datetime.now(UTC)
    if llm is not None and sources:
        doc = "\n".join(f"[{s.id}] {s.label}: {s.text}" for s in sources)
        try:
            reply = llm.complete(
                system=system,
                user=fixed_text(doc),  # computed facts and already-redacted quotes only
                purpose=purpose,
                actor_id=actor_id,
                json_schema=_SCHEMA,
                temperature=0.0,
            )
            bullets, dropped = check((reply.parsed or {}).get("bullets", []), sources)
            if bullets:
                return Brief(
                    bullets=bullets,
                    sources=list(sources),
                    model=reply.model,
                    dropped=dropped,
                    generated_at=now,
                )
        except Exception:  # the model is down or broke the schema: the template stands in
            pass
    return Brief(bullets=list(fallback), sources=list(sources), model=None, dropped=0, generated_at=now)


CASE_PURPOSE = Purpose.CASE_BRIEF
PORTFOLIO_PURPOSE = Purpose.PORTFOLIO_BRIEF


_FIELDS = (
    ("hardship_signal", "hardship"),
    ("stated_reason", "reason"),
    ("promise_intent", "promise"),
    ("promised_amount", "promised amount"),
    ("promised_date", "promised date"),
    ("dispute", "dispute"),
    ("cease_request", "asked to stop contact"),
    ("third_party_present", "third party"),
)


def case_sources(
    card: Any, extractions: Sequence[Any] = (), calls: Sequence[Any] = (), history: Any | None = None
) -> list[Source]:
    """Numbered sources for one case: facts from the card and history, then every quoted piece of evidence the
    extraction found in the case's notes and calls (redacted text, so safe for any model)."""
    facts: list[tuple[str, str]] = [
        ("Recommended action", card.headline if card.proposal else str(card.no_action_reason))
    ]
    if card.proposal is not None:
        facts.append(
            (
                "Tier",
                f"{card.proposal.tier.value}, released by "
                + (
                    "a specialist and a second person"
                    if card.proposal.tier.value == "red"
                    else "the agent or team lead"
                ),
            )
        )
        if card.proposal.sizing is not None:
            z = card.proposal.sizing
            facts.append(
                (
                    "Sized promise",
                    f"${z.amount} × {z.installments}, first due {z.due_date},"
                    f" spare cash about ${z.spare_cash_estimate}",
                )
            )
    if card.probabilities:
        best, wait = (
            card.probabilities[0],
            next((p for p in card.probabilities if p.action.value == "wait"), None),
        )
        line = f"{best.p_paid_14d:.0%} chance of payment in 14 days"
        facts.append(
            (
                "Model",
                line + (f" against {wait.p_paid_14d:.0%} if we wait" if wait and wait is not best else ""),
            )
        )
    if card.hardship_banner:
        facts.append(("Hardship", card.hardship_banner))
    for r in card.reasons[:2]:
        facts.append(("Reason", f"{r.sentence} (+{r.contribution_pts:.1f} pts)"))
    if history is not None and history.contacts:
        facts.append(
            (
                "History",
                f"{history.contacts} contacts; promises kept {history.promises_kept}"
                f" of {history.promises_kept + history.promises_broken}",
            )
        )
    out = [
        Source(id=f"F{i}", kind="fact", label=label, text=text) for i, (label, text) in enumerate(facts, 1)
    ]
    seen: set[str] = set()
    items = [("Note", x.source_id, x) for x in extractions] + [
        ("Call", c.voice_sample_id, c.extraction) for c in calls if c.extraction
    ]
    for kind, sid, x in items:
        for field, label in _FIELDS:
            v = getattr(x, field, None)
            ev = getattr(v, "evidence", None)
            if ev is None or ev.quote in seen or len(out) >= 24:
                continue
            seen.add(ev.quote)
            out.append(
                Source(
                    id=f"E{sum(s.kind == 'quote' for s in out) + 1}",
                    kind="quote",
                    label=f"{kind} {sid} · {label}",
                    text=ev.quote,
                )
            )
    return out


def case_fallback(sources: Sequence[Source]) -> list[Bullet]:
    """The template brief: the recommendation, the first thing the customer said, the top reason."""
    pick = [next((s for s in sources if s.label == lab), None) for lab in ("Recommended action", "Reason")]
    quote = next((s for s in sources if s.kind == "quote"), None)
    out = []
    if pick[0]:
        out.append(Bullet(text=pick[0].text, cites=[pick[0].id]))
    if quote:
        out.append(Bullet(text=f"The customer said: “{quote.text}”", cites=[quote.id]))
    if pick[1]:
        out.append(Bullet(text=pick[1].text, cites=[pick[1].id]))
    return out


def portfolio_sources(p: Any) -> list[Source]:
    """Numbered facts from the portfolio overview (kept.app.portfolio), written as the page writes them."""
    facts = [
        ("Open cases", f"{p.cases:,} open cases tonight"),
        ("Balance at risk", f"${p.balance:,.0f} overdue"),
        ("Expected recovery", f"${p.expected:,.0f} expected recovery over waiting"),
        (
            "With an action",
            f"{p.actionable:,} cases ({p.actionable / p.cases:.0%}) have an action"
            if p.cases
            else "no cases",
        ),
        ("Red", f"{p.red:,} Red cases need a hardship specialist and a second person"),
        ("Hard stops", f"{p.hard_stops:,} cases get no contact (cease, insolvency, deceased)"),
    ]
    facts += [
        (
            c.test_cell.replace("_", " "),
            f"{c.test_cell} keeps {c.kept_rate:.1%} of promises"
            f" (95% CI {c.kept_lo:.1%}–{c.kept_hi:.1%}, {c.promises:,} promises)",
        )
        for c in p.ab_test
    ]
    facts += [(i.title, i.body) for i in p.insights]
    return [
        Source(id=f"F{i}", kind="fact", label=label, text=text) for i, (label, text) in enumerate(facts, 1)
    ]


def portfolio_fallback(sources: Sequence[Source]) -> list[Bullet]:
    return [Bullet(text=s.text, cites=[s.id]) for s in sources[:3]]
