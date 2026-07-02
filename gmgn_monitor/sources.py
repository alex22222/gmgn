from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Protocol

from .serialization import load_jsonl


class CandidateSource(Protocol):
    def load(self) -> Iterable[dict]:
        """Yield raw candidate dictionaries without side effects."""


class JsonlCandidateSource:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> Iterable[dict[str, Any]]:
        yield from load_jsonl(self.path)


def load_events(path: Path) -> list[dict[str, Any]]:
    """Load all JSONL records from path into a list."""
    return list(load_jsonl(path))
