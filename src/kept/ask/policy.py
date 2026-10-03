"""Step 3c: policy questions search current documents in LanceDB and cite the section.

reference_documents has doc_id, version, effective_date, superseded_by and section_ids
("§4.1"...). Old versions are kept on purpose "to test retrieval of current version":
a document's effective_to is the effective_date of the document that supersedes it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from kept.contracts.ask import Citation

_OPEN_END = "9999-12-31"  # effective_to of a document that is still current (ISO strings sort as dates)
_SNIPPET_CHARS = 1500
_SPLIT_OVER = 800  # a section longer than this is split into its paragraphs (FAQ answers, long policies)
# When documents disagree the policy wins: FAQs, call scripts and incident notes lag behind it.
_LOW_AUTHORITY = frozenset({"faq", "call_script", "incident_report", "release_note"})


@dataclass(frozen=True, slots=True)
class PolicyChunk:
    document_id: str
    section: str
    text: str
    effective_from: date
    effective_to: date | None  # None = still current
    doc_type: str = ""  # reference_documents.doc_type: policy, procedure, faq, script ...


def effective_windows(docs: list[dict[str, object]]) -> dict[str, tuple[date, date | None]]:
    """doc_id -> (effective_from, effective_to) from reference_documents rows, following
    superseded_by. A superseded_by that names an unknown doc -> ValueError."""
    starts = {str(d["doc_id"]): date.fromisoformat(str(d["effective_date"])) for d in docs}
    out: dict[str, tuple[date, date | None]] = {}
    for d in docs:
        newer = str(d.get("superseded_by") or "").strip()
        if newer and newer not in starts:
            raise ValueError(f"{d['doc_id']} is superseded by unknown document {newer!r}")
        out[str(d["doc_id"])] = (starts[str(d["doc_id"])], starts[newer] if newer else None)
    return out


_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.M)


def chunk_document(
    document_id: str,
    markdown: str,
    *,
    effective_from: date,
    effective_to: date | None,
    doc_type: str = "",
) -> list[PolicyChunk]:
    """Split on headings; every chunk keeps its section number/title. No empty chunks.
    A long section is split on blank lines, and an FAQ answer ("**Q2. ...") adds its number to the section.
    ponytail: text before the first heading (a disclaimer line) is dropped."""
    marks = list(_HEADING.finditer(markdown))
    ends = [m.start() for m in marks[1:]] + ([len(markdown)] if marks else [])
    sections = [(m[1], markdown[m.end() : end].strip()) for m, end in zip(marks, ends, strict=True)] or [
        (document_id, markdown.strip())  # no headings: the whole document is one section
    ]
    out: list[PolicyChunk] = []
    for section, body in sections:
        parts = [p.strip() for p in re.split(r"\n\s*\n", body)] if len(body) > _SPLIT_OVER else [body]
        for part in filter(None, parts):
            q = re.match(r"\*\*(Q\d+)\.", part)
            label = f"{section} {q[1]}" if q else section
            out.append(PolicyChunk(document_id, label, part, effective_from, effective_to, doc_type))
    return out


class PolicyIndex:
    """LanceDB full-text (BM25) index over policy sections. Keyword search, stemmed, no model download;
    ponytail: swap in embeddings if recall on paraphrased questions is poor."""

    def __init__(self, path: Path) -> None:
        import lancedb  # the `ask` extra

        self._db = lancedb.connect(str(path))

    def _has_table(self) -> bool:
        return "policy" in self._db.list_tables().tables

    def add(self, chunks: list[PolicyChunk]) -> None:
        rows = [
            {
                "document_id": c.document_id,
                "section": c.section,
                "text": c.text,
                "doc_type": c.doc_type,
                "search_text": f"{c.section}\n{c.text}",  # the heading is searchable too
                "effective_from": c.effective_from.isoformat(),
                "effective_to": c.effective_to.isoformat() if c.effective_to else _OPEN_END,
            }
            for c in chunks
        ]
        if not rows:
            return
        if self._has_table():
            table = self._db.open_table("policy")
            table.add(rows)
        else:
            table = self._db.create_table("policy", rows)
        table.create_fts_index("search_text", replace=True)

    def search(self, query: str, *, as_of: date, k: int = 3) -> list[Citation]:
        """Only chunks current on as_of (effective_from <= as_of < effective_to)."""
        if not self._has_table():
            return []
        day = as_of.isoformat()  # a date, so safe to put in the filter
        hits: list[dict[str, Any]] = (
            self._db.open_table("policy")
            .search(query, query_type="fts")
            .where(f"effective_from <= '{day}' AND effective_to > '{day}'", prefilter=True)
            .limit(max(k * 3, 10))  # over-fetch, then let authority reorder
            .to_list()
        )
        hits.sort(key=lambda h: h["doc_type"] in _LOW_AUTHORITY)  # stable: BM25 order within a group
        return [
            Citation(
                document_id=h["document_id"],
                section=h["section"],
                effective_from=date.fromisoformat(h["effective_from"]),
                snippet=h["text"][:_SNIPPET_CHARS],
            )
            for h in hits[:k]
        ]


def build_policy_index(index: PolicyIndex, docs: list[dict[str, object]], docs_dir: Path) -> int:
    """Chunk every reference document (rows of reference_documents; file_path is relative to the
    release's files/ folder, and docs_dir is where its docs/ content was copied) and index it with
    its effective window. Returns the number of chunks."""
    windows = effective_windows(docs)
    chunks: list[PolicyChunk] = []
    for d in docs:
        start, end = windows[str(d["doc_id"])]
        text = (docs_dir / str(d["file_path"]).removeprefix("docs/")).read_text(encoding="utf-8")
        chunks += chunk_document(
            str(d["doc_id"]),
            text,
            effective_from=start,
            effective_to=end,
            doc_type=str(d.get("doc_type", "")),
        )
    index.add(chunks)
    return len(chunks)
