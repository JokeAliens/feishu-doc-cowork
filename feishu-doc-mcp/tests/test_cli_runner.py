import json
import os
import sys

import pytest

from feishu_doc_mcp.cli_runner import run_lark_cli, unwrap
from feishu_doc_mcp.errors import CliExecError, LarkApiError

FAKE_BIN = os.path.join(os.path.dirname(__file__), "fake_lark_cli.py")


@pytest.fixture()
def fake_cli(tmp_path, monkeypatch):
    """Point run_lark_cli at the fake binary; return helpers to drive it."""
    log_path = tmp_path / "calls.jsonl"
    responses_path = tmp_path / "responses.json"
    monkeypatch.setenv("LARK_CLI_BIN", sys.executable)
    monkeypatch.setenv("LARK_CLI_BIN_ARGS", FAKE_BIN)
    monkeypatch.setenv("FAKE_LARK_LOG", str(log_path))
    monkeypatch.setenv("FAKE_LARK_RESPONSES", str(responses_path))

    def set_rules(rules):
        responses_path.write_text(json.dumps(rules, ensure_ascii=False), encoding="utf-8")

    def calls():
        if not log_path.exists():
            return []
        return [json.loads(line)["argv"] for line in log_path.read_text().splitlines()]

    return set_rules, calls


def test_unwrap_ok_returns_data():
    assert unwrap({"ok": True, "data": {"a": 1}}) == {"a": 1}


def test_unwrap_error_raises_with_hint():
    envelope = {
        "ok": False,
        "error": {
            "type": "api",
            "subtype": "permission_denied",
            "message": "no scope",
            "hint": "run: lark-cli auth login --scope docs:document.comment:read",
        },
    }
    with pytest.raises(LarkApiError) as exc_info:
        unwrap(envelope)
    err = exc_info.value
    assert err.code == "permission_denied"
    assert err.message == "no scope"
    assert err.hint == "run: lark-cli auth login --scope docs:document.comment:read"


def test_run_appends_format_json(fake_cli):
    set_rules, calls = fake_cli
    set_rules([{"argv_contains": ["auth", "status"], "stdout": {"ok": True, "data": {"x": 1}}, "exit": 0}])
    result = run_lark_cli(["auth", "status"])
    assert result["ok"] is True
    argv = calls()[0]
    assert "--format" in argv and "json" in argv
    assert argv.index("--format") < len(argv) - 1 and argv[argv.index("--format") + 1] == "json"


def test_run_nonzero_exit_raises_cli_exec(fake_cli):
    set_rules, _ = fake_cli
    set_rules([{"argv_contains": ["boom"], "stdout": {"ok": False}, "exit": 1}])
    with pytest.raises(CliExecError):
        run_lark_cli(["boom"])


def test_run_invalid_json_raises_cli_exec(fake_cli):
    set_rules, _ = fake_cli
    set_rules([{"argv_contains": ["garbage"], "stdout": "not json at all", "exit": 0}])
    with pytest.raises(CliExecError):
        run_lark_cli(["garbage"])


def test_run_dry_run_adds_flag(fake_cli):
    set_rules, calls = fake_cli
    set_rules([{"argv_contains": ["api"], "stdout": {"ok": True, "dry_run": True, "data": {}}, "exit": 0}])
    run_lark_cli(["api", "PATCH", "/open-apis/x"], dry_run=True)
    assert "--dry-run" in calls()[0]
