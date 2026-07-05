from __future__ import annotations

"""Loop Engineering structured logging system.

Provides per-loop JSONL log files with size-based rotation under
``logs/loop/``.  All entries are durable (fsync) and human-readable
via standard JSONL tooling.

Example usage::

    logger = get_loop_logger("data_quality")
    logger.log("warning", "completeness dropped", extra={"rate": 0.92})
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .file_io import durable_append_text


DEFAULT_LOG_DIR: Path = Path("logs/loop")
DEFAULT_MAX_SIZE: int = 10 * 1024 * 1024  # 10 MiB


class LoopLogger:
    """Structured logger for a single feedback loop.

    Writes JSONL-formatted entries to ``{log_dir}/{loop_name}.log``.
    Automatically rotates when the file reaches *max_size*.
    """

    def __init__(self, loop_name: str, log_dir: Path | None = None, max_size: int = DEFAULT_MAX_SIZE) -> None:
        self.loop_name = loop_name
        self.log_dir = log_dir or DEFAULT_LOG_DIR
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._file_path = self.log_dir / f"{loop_name}.log"
        self._max_size = max_size

    @property
    def file_path(self) -> Path:
        """Return the primary log file path."""
        return self._file_path

    def log(self, level: str, message: str, extra: dict[str, Any] | None = None) -> None:
        """Append a structured JSONL entry to the log file.

        *level* should be one of ``debug``, ``info``, ``warning``,
        ``error``, ``critical``.
        """
        entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "loop": self.loop_name,
            "level": level,
            "message": message,
        }
        if extra:
            entry["extra"] = extra
        line = json.dumps(entry, ensure_ascii=False, sort_keys=True)
        self._rotate_if_needed()
        durable_append_text(line + "\n", self._file_path)

    def _rotate_if_needed(self) -> None:
        """Rotate the log file when it exceeds *max_size*."""
        if self._file_path.exists() and self._file_path.stat().st_size >= self._max_size:
            rotated = self._file_path.with_suffix(".log.1")
            if rotated.exists():
                rotated.unlink()
            os.rename(self._file_path, rotated)

    def read_logs(self) -> list[dict[str, Any]]:
        """Read and parse all JSONL entries from the primary log file.

        Returns an empty list when the file does not exist.
        """
        if not self._file_path.exists():
            return []
        text = self._file_path.read_text(encoding="utf-8")
        records: list[dict[str, Any]] = []
        for line in text.strip().split("\n"):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return records

    def clear_logs(self) -> None:
        """Remove the primary log file and its rotation backup."""
        if self._file_path.exists():
            self._file_path.unlink()
        rotated = self._file_path.with_suffix(".log.1")
        if rotated.exists():
            rotated.unlink()

    def log_count(self) -> int:
        """Return the number of valid JSONL entries in the primary log."""
        return len(self.read_logs())


def get_loop_logger(loop_name: str, log_dir: Path | None = None) -> LoopLogger:
    """Factory: create a :class:`LoopLogger` for *loop_name*."""
    return LoopLogger(loop_name, log_dir=log_dir)
