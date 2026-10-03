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

    version: str = "presidio-v2"

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
        results = [r for r in results if not any(r.start < e and s < r.end for s, e in kept_spans)]
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

_PLACEHOLDER = re.compile(r"<[A-Z_]+>")
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

    def rec(entity: str, regex: str, score: float, context: list[str]) -> PatternRecognizer:
        return PatternRecognizer(
            supported_entity=entity,
            patterns=[Pattern(entity.lower(), regex, score)],
            context=context,
            supported_language=language,
        )

    date = (
        r"\b(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4}"
        r"|\d{1,2}\s+[A-Za-z]{3,9}\.?,?\s+\d{4}|[A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{4})\b"
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
        # Card numbers in notes need not pass Luhn (the built-in recognizer requires it; fr has none).
        rec(
            "CREDIT_CARD",
            r"(?<!\d)\d{4}[- ]\d{4}[- ]\d{4}[- ]\d{4}(?!\d)|(?<!\d)\d{15,16}(?!\d)",
            0.6,
            ["card", "carte"],
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
        rec(
            "DATE_OF_BIRTH",
            date,
            0.05,
            ["dob", "born", "birth", "birthday", "birthdate", "ddn", "naissance", "né", "née"],
        ),
    ]
