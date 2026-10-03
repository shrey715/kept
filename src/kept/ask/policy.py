"""Step 3c: policy questions search current documents in LanceDB and cite the section.

reference_documents has doc_id, version, effective_date, superseded_by and section_ids
("§4.1"...). Old versions are kept on purpose "to test retrieval of current version":
a document's effective_to is the effective_date of the document that supersedes it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from kept.contracts.ask import Citation


@dataclass(frozen=True, slots=True)
class PolicyChunk:
    document_id: str
    section: str
    text: str
    effective_from: date
    effective_to: date | None  # None = still current


def effective_windows(docs: list[dict[str, object]]) -> dict[str, tuple[date, date | None]]:
    """doc_id -> (effective_from, effective_to) from reference_documents rows, following
    superseded_by. A superseded_by that names an unknown doc -> ValueError."""
    raise NotImplementedError("Track B")


def chunk_document(
    document_id: str, markdown: str, *, effective_from: date, effective_to: date | None
) -> list[PolicyChunk]:
    """Split on headings; every chunk keeps its section number/title. No empty chunks."""
    raise NotImplementedError("Track B")


class PolicyIndex:
    def __init__(self, path: Path) -> None:
        raise NotImplementedError("Track B")

    def add(self, chunks: list[PolicyChunk]) -> None:
        raise NotImplementedError("Track B")

    def search(self, query: str, *, as_of: date, k: int = 3) -> list[Citation]:
        """Only chunks current on as_of (effective_from <= as_of < effective_to)."""
        raise NotImplementedError("Track B")
