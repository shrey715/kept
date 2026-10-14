# ruff: noqa: E501  (SQL strings and prompts)
"""Step 3a, widened: reviewed SQL templates and prompt context, so the LLM writes free SQL only as a last resort.

The ladder for a data question:
  1. a certified metric (metric_definitions, kept.ask.certified) or one of the TEMPLATES below: reviewed SQL, the
     LLM only picks it and fills filters, groups and dates;
  2. a lookup: the LLM writes SQL, helped by `date_hints` (dates worked out in code, never by the model) and
     `examples` (our own worked question -> SQL pairs, the closest ones for this question);
  3. a clarifying question, then a refusal.

Templates cover recurring questions the release's 15 metrics don't: charge-offs in a window, the 30-day cure
rate, the share of calls outside permitted hours. Each was checked against the raw release data.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, timedelta

from kept.ask.metrics import CertifiedQuery, MetricDefinition

_HOLDS = ("NOT coalesce(insolvency_hold_flag, false)", "NOT coalesce(deceased_hold_flag, false)")
_CASE_COLS = frozenset(
    {"primary_product", "queue", "province_code", "current_bucket", "assignment_method", "hardship_flag"}
    | {"agent_vulnerable_certified"}
)


def _md(metric_id: str, name: str, synonyms: tuple[str, ...], example: str, unit: str) -> MetricDefinition:
    return MetricDefinition(
        metric_id,
        name,
        name,
        "",
        "",
        "",
        "",
        unit,
        "",
        synonyms,
        (),
        example,
        "Kept (reviewed template)",
        True,
    )


TEMPLATES: dict[str, tuple[MetricDefinition, CertifiedQuery]] = {
    "chargeoffs": (
        _md(
            "chargeoffs",
            "Charge-offs: accounts charged off and the amount, by product",
            ("charged off", "charge-offs", "write-offs", "written off"),
            "How many card and loan accounts were charged off in 2025, and for how much?",
            "count, cad",
        ),
        CertifiedQuery(
            "chargeoffs",
            """SELECT {group_by_select} count(*) AS n, sum(chargeoff_amount) AS total_chargeoff_amount
FROM (SELECT 'card' AS product, 'card' AS product_family, chargeoff_date, chargeoff_amount
        FROM silver.card_accounts WHERE chargeoff_flag
      UNION ALL
      SELECT product_type, 'loan', chargeoff_date, chargeoff_amount
        FROM silver.loan_accounts WHERE chargeoff_flag) t
WHERE 1=1 {where} {group_by}""",
            (),
            frozenset({"product", "product_family"}),
            frozenset({"product", "product_family"}),
            "chargeoff_date",
        ),
    ),
    "cure_rate_30d": (
        _md(
            "cure_rate_30d",
            "30-day cure rate: share of cases cured within 30 days of opening",
            ("cured within 30 days", "30-day cure", "cure within 30 days"),
            "What share of cases opened in June 2026 cured within 30 days?",
            "pct",
        ),
        CertifiedQuery(
            "cure_rate_30d",
            """SELECT {group_by_select} avg(CASE WHEN cure_flag AND days_to_cure <= 30 THEN 1.0 ELSE 0.0 END)
       AS cure_rate, count(*) AS n
FROM (SELECT k.primary_product, k.queue, k.province_code, k.current_bucket, k.assignment_method,
             k.test_cell, k.hardship_flag, k.cure_flag, k.days_to_cure, k.case_open_date, k.insolvency_hold_flag,
             k.deceased_hold_flag, a.vulnerable_customer_certified AS agent_vulnerable_certified
      FROM silver.collections_cases k LEFT JOIN silver.agents a ON a.agent_id = k.assigned_agent_id) t
WHERE 1=1 {where} {group_by}""",
            _HOLDS,
            _CASE_COLS | {"test_cell"},  # champion vs challengers
            _CASE_COLS | {"test_cell"},
            "case_open_date",
        ),
    ),
    "out_of_hours_rate": (
        _md(
            "out_of_hours_rate",
            "Out-of-hours rate: share of outbound calls placed outside permitted calling hours",
            ("outside permitted hours", "outside calling hours", "out of hours"),
            "What share of outbound calls in August 2026 were outside permitted hours, by province?",
            "pct",
        ),
        CertifiedQuery(
            "out_of_hours_rate",
            """SELECT {group_by_select} avg(CASE WHEN NOT within_permitted_hours_flag THEN 1.0 ELSE 0.0 END)
       AS out_of_hours_rate, count(*) AS n
FROM (SELECT h.direction, h.channel, h.within_permitted_hours_flag, h.contact_ts_local, h.contact_hour_local,
             h.agent_site, c.province_code, c.queue
      FROM silver.contact_history h JOIN silver.collections_cases c ON c.case_id = h.case_id) t
WHERE 1=1 {where} {group_by}""",
            ("direction = 'outbound'", "channel = 'call'"),
            frozenset({"province_code", "queue", "contact_hour_local", "agent_site"}),
            frozenset({"province_code", "queue", "contact_hour_local", "agent_site"}),
            "CAST(contact_ts_local AS DATE)",
        ),
    ),
    # Events on contacts: calls, disputes and complaints raised, right-party contacts, payments taken. One row per
    # contact in contact_history, dated by the customer's local time (the data dictionary's rule).
    "contact_events": (
        _md(
            "contact_events",
            "Contact counts: calls, emails, texts; disputes and complaints raised; right-party contacts; by day",
            (
                "calls made",
                "contacts",
                "disputes raised",
                "complaints raised",
                "right party contacts",
                "payments taken",
                "outbound calls",
                "number of contacts",
                "per day",
                "each day",
            ),
            "How many outbound calls were made on each day from 20 to 26 September 2026?",
            "count",
        ),
        CertifiedQuery(
            "contact_events",
            """SELECT {group_by_select} count(*) AS n
FROM (SELECT CAST(contact_ts_local AS DATE) AS contact_date, channel, sub_channel, direction, agent_site,
             contact_hour_local, test_cell, dial_result, rpc_flag, dispute_raised_flag, complaint_raised_flag,
             hardship_mentioned_flag, cease_request_flag, ptp_made_flag, payment_taken_flag, interpreter_used_flag
      FROM silver.contact_history) t
WHERE 1=1 {where} {group_by}""",
            (),
            frozenset(
                {"channel", "sub_channel", "direction", "agent_site", "test_cell", "dial_result", "rpc_flag"}
                | {
                    "dispute_raised_flag",
                    "complaint_raised_flag",
                    "hardship_mentioned_flag",
                    "cease_request_flag",
                }
                | {"ptp_made_flag", "payment_taken_flag", "interpreter_used_flag", "contact_hour_local"}
            ),
            frozenset(
                {"contact_date", "channel", "sub_channel", "direction", "agent_site", "contact_hour_local"}
            )
            | frozenset({"test_cell", "dial_result"}),
            "contact_date",
        ),
    ),
    # QA: calls a reviewer scored (qa_selected_flag with a score), averaged; the site is the agent's at the time.
    "qa_score": (
        _md(
            "qa_score",
            "Average QA score of reviewed calls, by agent site or day",
            ("qa score", "quality score", "reviewed calls", "call quality", "quality assurance"),
            "What was the average QA score of reviewed calls in September 2026, by agent site?",
            "score",
        ),
        CertifiedQuery(
            "qa_score",
            """SELECT {group_by_select} avg(qa_score) AS avg_qa_score, count(*) AS n
FROM (SELECT CAST(contact_ts_local AS DATE) AS contact_date, agent_site, channel, direction, qa_score
      FROM silver.contact_history WHERE qa_selected_flag AND qa_score IS NOT NULL) t
WHERE 1=1 {where} {group_by}""",
            ("agent_site IS NOT NULL",),
            frozenset({"agent_site", "channel", "direction"}),
            frozenset({"agent_site", "contact_date", "channel"}),
            "contact_date",
        ),
    ),
    # Open cases (outcome not yet set), counted by the case's own columns.
    "open_cases": (
        _md(
            "open_cases",
            "Open collections cases: how many, by bucket, queue, product or province",
            ("open cases", "cases open", "how many cases", "caseload", "number of cases"),
            "How many collections cases are open today, by current bucket?",
            "count",
        ),
        CertifiedQuery(
            "open_cases",
            """SELECT {group_by_select} count(*) AS open_cases
FROM silver.collections_cases WHERE outcome IS NULL {where} {group_by}""",
            (),
            _CASE_COLS,
            _CASE_COLS,
            "case_open_date",
        ),
    ),
    # Deposit overdrafts past due (overdraft_dpd, added to deposit_accounts), at a snapshot.
    "overdraft_past_due": (
        _md(
            "overdraft_past_due",
            "Deposit accounts with an overdraft past due, by overdraft bucket",
            ("overdraft past due", "overdrawn accounts", "overdraft bucket", "overdraft delinquency"),
            "How many deposit accounts have an overdraft that is past due today, by overdraft bucket?",
            "count",
        ),
        CertifiedQuery(
            "overdraft_past_due",
            """SELECT {group_by_select} count(*) AS accounts
FROM silver.deposit_accounts WHERE overdraft_dpd >= 1 {where} {group_by}""",
            (),
            frozenset({"product_type", "overdraft_dpd_bucket"}),
            frozenset({"product_type", "overdraft_dpd_bucket"}),
            "snapshot_date",
        ),
    ),
}

# ---------------------------------------------------------------- dates, worked out in code
_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
_MONTHS |= {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}
_M = r"(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\.?"
_NUM = {"one": 1, "two": 2, "three": 3, "six": 6, "nine": 9, "twelve": 12}


def _month_end(y: int, m: int) -> date:
    return date(y, m, calendar.monthrange(y, m)[1])


def _minus_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 - n, 12)
    y, m = d.year + y, m + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def resolve_dates(question: str, as_of: date | None) -> list[tuple[str, date, date]]:
    """(phrase, first day, last day), both inclusive, for the date phrases in a question. Covers what the
    benchmark and agents ask: "September 2026", "July-September 2026", "between 15 and 22 September 2026",
    "the 8 days before", "the 12 months to 28 September 2026", "end of March 2026", "last month"."""
    q, out = question.lower(), []
    taken: list[tuple[int, int]] = []

    def add(m: re.Match[str], start: date, end: date) -> None:
        if not any(a <= m.start() < b for a, b in taken):
            taken.append(m.span())
            out.append((question[m.start() : m.end()].strip(), start, end))

    for m in re.finditer(rf"(\d+|{'|'.join(_NUM)}) months? to (\d{{1,2}}) {_M} (\d{{4}})", q):
        end = date(int(m[4]), _MONTHS[m[3]], int(m[2]))
        n = int(m[1]) if m[1].isdigit() else _NUM[m[1]]
        add(m, _minus_months(end, n) + timedelta(days=1), end)
    for m in re.finditer(rf"(?:between )?(\d{{1,2}})(?: and | ?- ?| to )(\d{{1,2}}) {_M} (\d{{4}})", q):
        y, mo = int(m[4]), _MONTHS[m[3]]
        add(m, date(y, mo, int(m[1])), date(y, mo, int(m[2])))
    for m in re.finditer(rf"end of {_M} (\d{{4}})", q):
        d = _month_end(int(m[2]), _MONTHS[m[1]])
        add(m, d, d)
    for m in re.finditer(rf"{_M} ?[-–] ?{_M} (\d{{4}})", q):
        y = int(m[3])
        add(m, date(y, _MONTHS[m[1]], 1), _month_end(y, _MONTHS[m[2]]))
    for m in re.finditer(rf"(?<![\d-] ){_M} (\d{{4}})", q):
        y, mo = int(m[2]), _MONTHS[m[1]]
        add(m, date(y, mo, 1), _month_end(y, mo))
    for m in re.finditer(r"\b(?:in|during|for) (20\d\d)\b", q):  # a bare year: "opened in 2026"
        y = int(m[1])
        add(m, date(y, 1, 1), date(y, 12, 31))
    for m in re.finditer(r"the (\d+) days before", q):  # the window just before the last range found
        if out:
            first = min(s for _, s, _ in out)
            add(m, first - timedelta(days=int(m[1])), first - timedelta(days=1))
    if as_of is not None:  # "today" stays the as-of date the router already has: not a date range
        for m in re.finditer(r"\blast month\b", q):
            prev = as_of.replace(day=1) - timedelta(days=1)
            add(m, prev.replace(day=1), prev)
    return out


def date_hints(question: str, as_of: date | None) -> str:
    """The resolved dates as prompt text ("" when the question names none)."""
    found = resolve_dates(question, as_of)
    if not found:
        return ""
    lines = [
        f'- "{p}": {s.isoformat()}' + (" (one day)" if s == e else f" to {e.isoformat()} (both inclusive)")
        for p, s, e in found
    ]
    compare = ""
    if len(found) >= 2 and COMPARE.search(question):  # "..., compared with the 8 days before"
        compare = (
            "\nThe question compares these periods: return one row per period, with a first column naming the"
            " period (its dates), then the measure. Count each period over its own dates only."
        )
    return (
        "\nDates in the question, already worked out (use exactly these; never compute dates yourself):\n"
        + ("\n".join(lines))
        + compare
    )


COMPARE = re.compile(r"\b(compared?|versus|vs\.?|against)\b|days before|the previous|the prior", re.I)


# ---------------------------------------------------------------- worked examples for free SQL
EXAMPLES: tuple[tuple[str, str], ...] = (
    (
        "What share of outbound calls in August 2026 reached the right party, by agent site?",
        "SELECT a.site, round(100.0 * avg(CASE WHEN h.rpc_flag THEN 1 ELSE 0 END), 2) AS rpc_pct, count(*) AS n\n"
        "FROM silver.contact_history h LEFT JOIN silver.agents a ON a.agent_id = h.agent_id\n"
        "WHERE h.direction = 'outbound' AND h.channel = 'call'\n"
        "  AND CAST(h.contact_ts_local AS DATE) BETWEEN DATE '2026-08-01' AND DATE '2026-08-31'\n"
        "GROUP BY a.site ORDER BY a.site",
    ),
    (
        "How many outbound contact attempts did open cases get on average, by queue?",
        "SELECT k.queue, avg(coalesce(c.attempts, 0)) AS attempts_per_case, count(*) AS n\n"
        "FROM silver.collections_cases k\n"
        "LEFT JOIN (SELECT case_id, count(*) AS attempts FROM silver.contact_history\n"
        "           WHERE direction = 'outbound' AND channel <> 'system' GROUP BY case_id) c ON c.case_id = k.case_id\n"
        "WHERE k.outcome IS NULL GROUP BY k.queue ORDER BY k.queue",
    ),
    (
        "How many complaints were raised between 1 and 7 September 2026, compared with the 7 days before?",
        "SELECT count(*) FILTER (WHERE CAST(contact_ts_local AS DATE) BETWEEN DATE '2026-09-01' AND DATE '2026-09-07')"
        " AS complaints_period,\n"
        "       count(*) FILTER (WHERE CAST(contact_ts_local AS DATE) BETWEEN DATE '2026-08-25' AND DATE '2026-08-31')"
        " AS complaints_before\n"
        "FROM silver.contact_history WHERE complaint_raised_flag",
    ),
    (
        # a dispute is raised in a contact (call, message): count contact_history rows; contact_history has no
        # dispute type, so a late-fee dispute is any dispute_raised_flag contact (never collections_cases)
        "How many late-fee disputes were raised between 1 and 7 September 2026, compared with the 7 days before?",
        "SELECT count(*) FILTER (WHERE CAST(contact_ts_local AS DATE) BETWEEN DATE '2026-09-01' AND DATE '2026-09-07')"
        " AS disputes_period,\n"
        "       count(*) FILTER (WHERE CAST(contact_ts_local AS DATE) BETWEEN DATE '2026-08-25' AND DATE '2026-08-31')"
        " AS disputes_before\n"
        "FROM silver.contact_history WHERE dispute_raised_flag",
    ),
    (
        # every link sent counts, clicked or not: no filter on what happened after the click
        "What share of payment links sent by SMS in August 2026 were clicked?",
        "SELECT round(100.0 * avg(CASE WHEN link_clicked_flag THEN 1 ELSE 0 END), 2) AS clicked_pct, count(*) AS links\n"
        "FROM silver.contact_history\n"
        "WHERE channel = 'sms' AND payment_link_id IS NOT NULL\n"
        "  AND CAST(contact_ts_local AS DATE) BETWEEN DATE '2026-08-01' AND DATE '2026-08-31'",
    ),
    (
        "How many open cases have a dispute flag, by queue?",
        "SELECT queue, count(*) AS cases FROM silver.collections_cases\n"
        "WHERE outcome IS NULL AND dispute_flag GROUP BY queue ORDER BY queue",
    ),
    (
        "How much was paid against promises due in August 2026, by product?",
        "SELECT product, sum(amount_paid_against) AS paid_cad, count(*) AS n FROM silver.promises_to_pay\n"
        "WHERE ptp_due_date BETWEEN DATE '2026-08-01' AND DATE '2026-08-31' GROUP BY product ORDER BY product",
    ),
    (
        "What is the average days past due of open cases by province?",
        "SELECT province_code, avg(current_dpd) AS avg_dpd, count(*) AS n FROM silver.collections_cases\n"
        "WHERE outcome IS NULL AND current_dpd IS NOT NULL GROUP BY province_code ORDER BY province_code",
    ),
    (
        "What share of cases opened in 2026 had a hardship programme accepted, by queue?",
        "SELECT queue, round(100.0 * avg(CASE WHEN hardship_program_accepted THEN 1 ELSE 0 END), 2) AS accepted_pct,"
        " count(*) AS n\nFROM silver.collections_cases\n"
        "WHERE case_open_date BETWEEN DATE '2026-01-01' AND DATE '2026-12-31' GROUP BY queue ORDER BY queue",
    ),
)
_WORD = re.compile(r"[a-z]+")
_STOP = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "by",
        "did",
        "do",
        "does",
        "for",
        "how",
        "in",
        "is",
        "of",
        "on",
        "or",
        "the",
        "to",
        "was",
        "were",
        "what",
        "which",
        "with",
    ]
)


def examples(question: str, k: int = 3) -> str:
    """The k worked examples that share the most words with the question, as prompt text."""
    words = set(_WORD.findall(question.lower())) - _STOP
    ranked = sorted(EXAMPLES, key=lambda e: -len(words & set(_WORD.findall(e[0].lower()))))
    return "\nWorked examples (same tables and conventions; adapt, don't copy):\n" + "\n\n".join(
        f"Q: {q}\nSQL:\n{sql}" for q, sql in ranked[:k]
    )
