"""Step 3c: policy questions search current documents in LanceDB and cite the section.

reference_documents has doc_id, version, effective_date, superseded_by and section_ids
("§4.1"...). Old versions are kept on purpose "to test retrieval of current version":
a document's effective_to is the effective_date of the document that supersedes it.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from kept.contracts.ask import Citation, SourceText

_OPEN_END = "9999-12-31"  # effective_to of a document that is still current (ISO strings sort as dates)
_SNIPPET_CHARS = 1500
_SPLIT_OVER = 800  # a section longer than this is split into its paragraphs (FAQ answers, long policies)
# When documents disagree the policy wins: FAQs and call scripts lag behind it. Incident reports and release
# notes are not versions of a policy, so they are not demoted: for "why did X happen" they are the answer.
_LOW_AUTHORITY = frozenset({"faq", "call_script"})


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


EMBED_MODEL = os.environ.get("KEPT_EMBED_MODEL", "BAAI/bge-m3")  # multilingual: French sections, paraphrases
_RRF_K = 60  # reciprocal rank fusion's usual constant


def local_embedder(model: str = EMBED_MODEL) -> Callable[[list[str]], list[list[float]]] | None:
    """The embedding model if it's already on this machine (never downloads), else None: search is then
    BM25 only, exactly as before. GPU when there is one."""
    try:
        import torch
        from sentence_transformers import SentenceTransformer

        device = "cuda" if torch.cuda.is_available() else "cpu"
        st = SentenceTransformer(model, device=device, local_files_only=True)
    except Exception:
        return None

    def embed(texts: list[str]) -> list[list[float]]:
        return st.encode(texts, normalize_embeddings=True, batch_size=16).tolist()  # type: ignore[no-any-return]

    return embed


class PolicyIndex:
    """LanceDB index over policy sections: BM25 full text, plus embeddings when a local model is there
    (hybrid: the rankings fused by reciprocal rank), so a French section or a paraphrase is still found."""

    def __init__(self, path: Path, embed: Callable[[list[str]], list[list[float]]] | None = None) -> None:
        import lancedb  # the `ask` extra

        self._db = lancedb.connect(str(path))
        self._embed = embed

    def _has_table(self) -> bool:
        return "policy" in self._db.list_tables().tables

    def add(self, chunks: list[PolicyChunk]) -> None:
        rows: list[dict[str, Any]] = [
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
        if self._embed is not None:
            for r, v in zip(rows, self._embed([r["search_text"] for r in rows]), strict=True):
                r["vector"] = v
        if self._has_table():
            table = self._db.open_table("policy")
            table.add(rows)
        else:
            table = self._db.create_table("policy", rows)
        table.create_fts_index("search_text", replace=True)

    def search(self, query: str, *, as_of: date, k: int = 3, mode: str = "hybrid") -> list[Citation]:
        """Only chunks current on as_of (effective_from <= as_of < effective_to). `mode` is for the
        retrieval benchmark (scripts/decision_B6.py): "bm25" or "dense" use one ranking, live is "hybrid"."""
        if not self._has_table():
            return []
        day = as_of.isoformat()  # a date, so safe to put in the filter
        current = f"effective_from <= '{day}' AND effective_to > '{day}'"
        table, n = self._db.open_table("policy"), max(k * 6, 20)  # over-fetch, then let authority reorder
        hits: list[dict[str, Any]] = (
            table.search(query, query_type="fts").where(current, prefilter=True).limit(n).to_list()
            if mode != "dense"
            else []
        )
        if mode != "bm25" and self._embed is not None and "vector" in table.schema.names:
            vector = self._embed([query])[0]
            by_vector: Any = table.search(vector)  # a vector query (the stubs type it as the generic builder)
            near = by_vector.distance_type("cosine").where(current, prefilter=True).limit(n).to_list()
            score: dict[tuple[str, str, str, str], float] = {}
            rows: dict[tuple[str, str, str, str], dict[str, Any]] = {}
            for ranked in (hits, near):
                for rank, h in enumerate(ranked):
                    key = (h["document_id"], h["section"], h["effective_from"], h["text"][:80])
                    score[key] = score.get(key, 0.0) + 1 / (_RRF_K + rank + 1)
                    rows.setdefault(key, h)
            hits = [rows[key] for key in sorted(score, key=score.__getitem__, reverse=True)]
        hits.sort(key=lambda h: h["doc_type"] in _LOW_AUTHORITY)  # stable: fused order within a group
        return [
            Citation(
                document_id=h["document_id"],
                section=h["section"],
                effective_from=date.fromisoformat(h["effective_from"]),
                snippet=h["text"][:_SNIPPET_CHARS],
            )
            for h in hits[:k]
        ]

    def source(self, document_id: str, section: str, effective_from: date, snippet: str) -> SourceText | None:
        """The whole document version a citation came from, with the cited passage located, so anyone can
        check the quote is really there. None if that document version isn't indexed.
        ponytail: scans the table (a few hundred chunks); filter in LanceDB if the corpus grows."""
        if not self._has_table():
            return None
        start = effective_from.isoformat()
        rows = [
            r
            for r in self._db.open_table("policy").to_arrow().to_pylist()  # insertion order = document order
            if r["document_id"] == document_id and r["effective_from"] == start
        ]
        if not rows:
            return None
        text, at = "", None
        for r in rows:
            block = f"{r['section']}\n{r['text']}"
            if at is None and r["section"] == section and snippet in r["text"]:
                at = len(text) + len(r["section"]) + 1 + r["text"].index(snippet)
            text += block + "\n\n"
        end = rows[0]["effective_to"]
        return SourceText(
            title=document_id,
            text=text.rstrip(),
            highlight_start=at,
            highlight_end=None if at is None else at + len(snippet),
            effective_from=effective_from,
            effective_to=None if end == _OPEN_END else date.fromisoformat(end),
        )


def build_policy_index(
    index: PolicyIndex,
    docs: list[dict[str, object]],
    docs_dir: Path,
    ops_events: list[dict[str, object]] | None = None,
) -> int:
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
    chunks += ops_event_chunks(ops_events or [])
    index.add(chunks)
    return len(chunks)


def ops_event_chunks(events: list[dict[str, object]]) -> list[PolicyChunk]:
    """One chunk per operations event (ops_events): an outage, a release, a policy change. They answer "why
    did X change on that day?", and carry the dated facts the incident report only summarises."""
    out = []
    for e in events:
        start = str(e["start_ts"])
        kind = str(e["event_type"]).replace("_", " ")
        text = (
            f"{e['description']}. A {kind} on {e['system']} from {start} to {e['end_ts']} "
            f"(severity {e['severity']}), affecting about {e['affected_customers_est']} customers."
        )
        out.append(
            PolicyChunk(
                str(e.get("reference_doc_id") or e["event_id"]),
                f"{e['event_id']}: {kind}",
                text,
                date.fromisoformat(start[:10]),
                None,
                "ops_event",
            )
        )
    return out
