"""Presidio redaction. The only place a RedactedText is constructed.

Inputs: agent_notes.note_text (redaction_status none / auto_redacted / needs_review),
call_transcripts turns[].text (pii_redaction_applied only covers DOB and national ID, so we
redact everything again), and contact_history.sms_reply_text. All three are Direct PII in
the data dictionary.
"""

from __future__ import annotations

import re
from typing import Any

from kept.contracts.features import RedactedText

# Entities we always remove. Canadian SIN and bank/card numbers need custom recognizers.
ENTITIES = (
    "PERSON",
    "PHONE_NUMBER",
    "EMAIL_ADDRESS",
    "CREDIT_CARD",
    "CA_SIN",
    "IBAN_CODE",
    "BANK_ACCOUNT",
    "LOCATION",
    "DATE_OF_BIRTH",
    "CA_POSTAL_CODE",
    "IP_ADDRESS",
    "URL",
)


class PresidioRedactor:
    """Implements kept.contracts.interfaces.Redactor.

    Replaces each entity with a typed placeholder: <PERSON>, <PHONE_NUMBER> ...
    Must be idempotent: redact(redact(x).text).text == redact(x).text.
    Money amounts and ordinary dates (e.g. "3 Oct", "$140") are kept: extraction needs them.
    """

    version: str = "presidio-v7"

    def __init__(self, *, models: dict[str, str] | None = None) -> None:
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.nlp_engine import NlpEngineProvider
        from presidio_anonymizer import AnonymizerEngine

        models = models or SPACY_MODELS
        nlp = NlpEngineProvider(
            nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": lang, "model_name": m} for lang, m in models.items()],
            }
        ).create_engine()
        self._languages = tuple(models)
        self._analyzer = AnalyzerEngine(nlp_engine=nlp, supported_languages=list(models))
        for lang in models:
            for recognizer in _canadian_recognizers(lang):
                self._analyzer.registry.add_recognizer(recognizer)
        self._anonymizer = AnonymizerEngine()  # type: ignore[no-untyped-call]

    def redact(self, text: str) -> RedactedText:
        lang = "fr" if "fr" in self._languages and looks_french(text) else self._languages[0]
        results = self._analyzer.analyze(
            text=text,
            language=lang,
            entities=list(ENTITIES),
            score_threshold=_MIN_SCORE,
            allow_list=list(JARGON),
        )
        # Never touch a placeholder from an earlier pass: keeps redact() idempotent.
        kept_spans = [m.span() for m in _PLACEHOLDER.finditer(text)]
        kept_spans += [m.span() for m in _BANK_ID.finditer(text)]  # our own IDs are not PII
        results = [
            r
            for r in results
            if not any(r.start < e and s < r.end for s, e in kept_spans)
            and (r.entity_type not in _NER_ENTITIES or _looks_like_name(text[r.start : r.end]))
            and not _inside_decimal(text, r.start, r.end)
        ]
        if not results:
            return RedactedText(text=text, redactor_version=self.version)
        out = self._anonymizer.anonymize(text=text, analyzer_results=results)  # type: ignore[arg-type]
        removed = tuple(sorted({item.entity_type for item in out.items}))
        return RedactedText(text=out.text, entity_types_removed=removed, redactor_version=self.version)


# 14% of agent notes are French (agent_notes.note_language). The English NER tags French words as
# names, so French text goes through the French model.
SPACY_MODELS = {"en": "en_core_web_lg", "fr": "fr_core_news_lg"}

_FRENCH_WORDS = frozenset(
    [
        "le",
        "la",
        "les",
        "de",
        "du",
        "des",
        "et",
        "au",
        "aux",
        "un",
        "une",
        "pas",
        "est",
        "à",
        "client",
        "cliente",
        "paie",
        "appel",
        "appels",
        "demande",
        "parlé",
        "réponse",
        "avec",
        "pour",
        "sur",
        "depuis",
        "prochaine",
        "laissé",
        "conjoint",
        "promesse",
        "paiement",
        "lien",
        "envoyé",
        "si",
        "peut",
        "être",
        "en",
        "son",
        "réf",
        "équipe",
        "difficultés",
        "perdu",
        "emploi",
        "rappel",
        "prévu",
        "appelé",
        "maison",
        "travail",
        "heures",
        "moins",
        "mois",
        "par",
        "va",
        "après",
    ]
)


def looks_french(text: str) -> bool:
    """Share of common French words. ponytail: word-list heuristic; use a language-id model if
    mixed EN/FR notes redact badly."""
    words = re.findall(r"[a-zà-ÿ']+", text.lower())
    return bool(words) and sum(w in _FRENCH_WORDS for w in words) / len(words) >= 0.15


# Collections shorthand spaCy mistakes for names or places ("escalated to TL" -> <LOCATION>).
JARGON = ("TL", "CB", "PTP", "RPC", "NSF", "EI", "PAD", "DPD", "LVM", "VM", "TPI", "CX", "cust", "pmt")

# spaCy NER on agent shorthand tags typos ("cust caleld"), months ("Jun") and ALL-CAPS template
# phrases ("RAPPEL PRÉVU") as names and places. Keep an NER span only if it has a Titlecase word that
# isn't a month. ponytail: an all-caps name ("JOHN SMITH") passes unredacted; notes hold almost no
# names (transcripts do, in Titlecase). Add a name list if the PII spot-check finds one.
_NER_ENTITIES = frozenset({"PERSON", "LOCATION"})
_MONTH_WORDS = frozenset(
    [
        "jan",
        "feb",
        "mar",
        "apr",
        "may",
        "jun",
        "jul",
        "aug",
        "sep",
        "sept",
        "oct",
        "nov",
        "dec",
        "january",
        "february",
        "march",
        "april",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
        "janv",
        "févr",
        "fév",
        "avr",
        "mai",
        "juin",
        "juil",
        "août",
        "déc",
        "janvier",
        "février",
        "mars",
        "avril",
        "juillet",
        "septembre",
        "octobre",
        "novembre",
        "décembre",
    ]
)


def _inside_decimal(text: str, start: int, end: int) -> bool:
    """Digits right after "3." or right before ".5" are part of a number, not a card or phone: the Ask's
    result rows carry unrounded decimals (0.42059724349157736 read as a 17-digit card number)."""
    before = start >= 2 and text[start - 1] == "." and text[start - 2].isdigit()
    after = end + 1 < len(text) and text[end] == "." and text[end + 1].isdigit()
    # "0.4206 26120" read as a phone: a span that opens like a decimal (1-2 digits, ".", a digit) is a
    # number; dotted phones (416.555.0123) have 3 digits before the first dot
    opens_decimal = re.match(r"\d{1,2}\.\d", text[start:end]) is not None
    # "20687420.97" (a money total in a result row) read as a phone: a span that is one plain decimal is an
    # amount; phones never have a single dot (416.555.0123 has two)
    plain_decimal = re.fullmatch(r"\d+\.\d+", text[start:end]) is not None
    return before or after or opens_decimal or plain_decimal


def _looks_like_name(span: str) -> bool:
    words = re.findall(r"[^\W\d_]+", span)
    return any(w[0].isupper() and w[1:].islower() and w.lower() not in _MONTH_WORDS for w in words)


_PLACEHOLDER = re.compile(r"<[A-Z_]+>")
# The bank's own record IDs (CS-2026-614370, N-0003433, G-004817, AG-2247, MIR-2540): Presidio's phone
# recognizer read the 10 digits of a case ID as a phone number, so Ask questions naming a case lost it.
_BANK_ID = re.compile(r"\b[A-Z]{1,4}-\d{3,}(?:-\d{3,})?\b")
# Weak patterns (bank accounts, DOBs) score 0.05 and only pass with a context word nearby (+0.35).
_MIN_SCORE = 0.35


def _luhn_ok(digits: str) -> bool:
    nums = [int(c) for c in digits if c.isdigit()]
    total = 0
    for i, n in enumerate(reversed(nums)):
        if i % 2:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


def _canadian_recognizers(language: str) -> list[Any]:
    from presidio_analyzer import Pattern, PatternRecognizer

    class SinRecognizer(PatternRecognizer):  # type: ignore[misc]
        def validate_result(self, pattern_text: str) -> bool:
            return _luhn_ok(pattern_text)

    class CardRecognizer(PatternRecognizer):  # type: ignore[misc]
        def validate_result(self, pattern_text: str) -> bool:
            return 12 <= sum(c.isdigit() for c in pattern_text) <= 19

    def rec(entity: str, regex: str, score: float, context: list[str]) -> PatternRecognizer:
        return PatternRecognizer(
            supported_entity=entity,
            patterns=[Pattern(entity.lower(), regex, score)],
            context=context,
            supported_language=language,
        )

    # A real month name, so "May 31 DOB 1987-01-13" can't match "31 DOB 1987" and hide the real DOB.
    month = "(?i:" + "|".join(sorted(_MONTH_WORDS, key=len, reverse=True)) + ")"
    date = (
        r"\b(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4}"
        rf"|\d{{1,2}}\s+{month}\.?,?\s+\d{{4}}|{month}\.?\s+\d{{1,2}},?\s+\d{{4}})\b"
    )
    return [
        SinRecognizer(
            supported_entity="CA_SIN",
            patterns=[Pattern("ca_sin", r"\b\d{3}[- ]?\d{3}[- ]?\d{3}\b", 0.5)],
            context=["sin", "nas", "social", "insurance", "assurance"],
            supported_language=language,
        ),
        rec(
            "CA_POSTAL_CODE",
            r"(?i)\b[ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTV-Z][ -]?\d[ABCEGHJ-NPRSTV-Z]\d\b",
            0.6,
            ["postal"],
        ),
        # Card numbers in notes need not pass Luhn (the built-in recognizer requires it; fr has none),
        # and synthetic notes drop digits ("4520 766 9760 7290"): 3-5 groups, 12-19 digits in all.
        CardRecognizer(
            supported_entity="CREDIT_CARD",
            patterns=[
                Pattern("card", r"(?<!\d)\d{2,5}(?:[- ]\d{2,5}){2,4}(?!\d)|(?<!\d)\d{13,19}(?!\d)", 0.6)
            ],
            context=["card", "carte"],
            supported_language=language,
        ),
        # North American numbers phonenumbers rejects (e.g. 555 exchanges in test data).
        rec(
            "PHONE_NUMBER",
            r"(?<!\d)(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}(?!\d)",
            0.5,
            ["phone", "cell", "call", "téléphone", "tél"],
        ),
        rec(
            "BANK_ACCOUNT",
            r"\b\d{5}[- ]?\d{3}[- ]?\d{5,12}\b|\b\d{7,12}\b",
            0.05,
            [
                "account",
                "acct",
                "chequing",
                "checking",
                "savings",
                "transit",
                "institution",
                "bank",
                "compte",
            ],
        ),
        rec("DATE_OF_BIRTH", date, 0.05, _DOB_WORDS),
        # Corrupted DOBs in synthetic notes ("DOB 206-12-25", "DOB 1987-0113"): digits and dashes, only
        # with a DOB word nearby.
        rec("DATE_OF_BIRTH", r"\b\d{2,6}[-/]\d{1,4}(?:[-/]\d{1,4})?\b", 0.05, _DOB_WORDS),
    ]


_DOB_WORDS = ["dob", "born", "birth", "birthday", "birthdate", "ddn", "naissance", "né", "née"]


def stored_redacted(text: str, redactor_version: str) -> RedactedText:
    """Rewrap text that PresidioRedactor already redacted and stored (text.redacted_notes Parquet),
    so batch jobs don't redact twice. Only for that output: anything else goes through redact()."""
    if not redactor_version.startswith("presidio-"):
        raise ValueError(f"not Presidio output: redactor_version={redactor_version!r}")
    return RedactedText(text=text, redactor_version=redactor_version)


def fixed_text(text: str) -> RedactedText:
    """A string written in our own code (an ops probe like "Reply with OK."), so there's nothing to redact.
    Never for customer text: notes, transcripts and questions go through PresidioRedactor."""
    return RedactedText(text=text, redactor_version="fixed-text")
