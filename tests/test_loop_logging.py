from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from gmgn_monitor.loop_logging import LoopLogger, get_loop_logger


@pytest.fixture
def temp_log_dir():
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


class TestLoopLogger:
    def test_creates_log_file(self, temp_log_dir: Path) -> None:
        logger = LoopLogger("data_quality", log_dir=temp_log_dir)
        logger.log("info", "test message")

        assert logger.file_path.exists()
        assert logger.file_path.name == "data_quality.log"

    def test_log_entry_is_valid_jsonl(self, temp_log_dir: Path) -> None:
        logger = LoopLogger("data_quality", log_dir=temp_log_dir)
        logger.log("info", "hello")

        records = logger.read_logs()
        assert len(records) == 1
        assert records[0]["loop"] == "data_quality"
        assert records[0]["level"] == "info"
        assert records[0]["message"] == "hello"
        assert "timestamp" in records[0]

    def test_log_with_extra(self, temp_log_dir: Path) -> None:
        logger = LoopLogger("score_validation", log_dir=temp_log_dir)
        logger.log("warning", "correlation dropped", extra={"r": 0.45})

        records = logger.read_logs()
        assert records[0]["extra"]["r"] == 0.45

    def test_multiple_logs_in_order(self, temp_log_dir: Path) -> None:
        logger = LoopLogger("system_health", log_dir=temp_log_dir)
        logger.log("info", "first")
        logger.log("info", "second")
        logger.log("info", "third")

        records = logger.read_logs()
        assert len(records) == 3
        assert [r["message"] for r in records] == ["first", "second", "third"]

    def test_log_count(self, temp_log_dir: Path) -> None:
        logger = LoopLogger("backtest", log_dir=temp_log_dir)
        logger.log("info", "one")
        logger.log("info", "two")

        assert logger.log_count() == 2

    def test_read_logs_returns_empty_when_missing(self, temp_log_dir: Path) -> None:
        logger = LoopLogger("missing", log_dir=temp_log_dir)
        assert logger.read_logs() == []
        assert logger.log_count() == 0

    def test_clear_logs_removes_file(self, temp_log_dir: Path) -> None:
        logger = LoopLogger("data_quality", log_dir=temp_log_dir)
        logger.log("info", "hello")
        logger.clear_logs()

        assert not logger.file_path.exists()

    def test_clear_logs_also_removes_rotated(self, temp_log_dir: Path) -> None:
        logger = LoopLogger("data_quality", log_dir=temp_log_dir)
        logger.log("info", "hello")
        rotated = logger.file_path.with_suffix(".log.1")
        rotated.write_text("old")
        logger.clear_logs()

        assert not logger.file_path.exists()
        assert not rotated.exists()

    def test_rotation(self, temp_log_dir: Path) -> None:
        logger = LoopLogger("data_quality", log_dir=temp_log_dir, max_size=10)
        logger.log("info", "x" * 50)
        logger.log("info", "y" * 50)

        assert logger.file_path.exists()
        rotated = logger.file_path.with_suffix(".log.1")
        assert rotated.exists()

    def test_invalid_json_line_skipped(self, temp_log_dir: Path) -> None:
        logger = LoopLogger("data_quality", log_dir=temp_log_dir)
        logger.file_path.write_text('not json\n{"valid": true}\n')

        records = logger.read_logs()
        assert len(records) == 1
        assert records[0]["valid"] is True


class TestGetLoopLogger:
    def test_factory_returns_logger(self, temp_log_dir: Path) -> None:
        logger = get_loop_logger("execution_quality", log_dir=temp_log_dir)
        logger.log("info", "factory test")

        assert logger.file_path.exists()
        assert logger.loop_name == "execution_quality"
