from __future__ import annotations

import json
from pathlib import Path

from gmgn_monitor.audit_log import append_audit_event, build_audit_report, read_audit_events


def test_append_and_read_audit_event(tmp_path: Path):
    append_audit_event(
        tmp_path,
        category="manual_config",
        action="leader_toggle",
        success=True,
        source="dashboard",
        actor="user",
        object_type="leader",
        object_id="Leader111",
        message="Leader 已启动",
        details={"enabled": True},
    )

    events = read_audit_events(tmp_path)

    assert len(events) == 1
    assert events[0]["category"] == "manual_config"
    assert events[0]["success"] is True
    assert events[0]["details"]["enabled"] is True
    raw = json.loads((tmp_path / "data/audit_events.jsonl").read_text(encoding="utf-8"))
    assert raw["object_id"] == "Leader111"


def test_build_audit_report_counts_categories_and_failures(tmp_path: Path):
    append_audit_event(
        tmp_path,
        category="copy_trade",
        action="auto_copy_sell",
        success=False,
        source="run_auto_copy_trading",
        object_type="token",
        object_id="Token111",
        message="Zero token balance",
    )
    append_audit_event(
        tmp_path,
        category="auto_trade",
        action="auto_buy",
        success=True,
        source="run_auto_copy_trading",
        object_type="token",
        object_id="Token222",
        message="自动买入已提交",
    )

    report = build_audit_report(tmp_path)

    assert report["total"] == 2
    assert report["successes"] == 1
    assert report["failures"] == 1
    assert report["categories"]["copy_trade"] == 1
    assert report["categories"]["auto_trade"] == 1
    assert report["recent_events"][0]["object_id"] == "Token222"
