import json
import os
import sys

import pytest

from feishu_doc_mcp.cli_runner import run_lark_cli, unwrap
from feishu_doc_mcp.errors import CliExecError, LarkApiError

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


def test_run_nonzero_exit_with_valid_envelope_returns_it(fake_cli):
    """lark-cli exits 1 for API-level failures with a valid envelope
    (observed live 2026-10-12: +update no-op degrade); the envelope must
    reach unwrap so the caller gets code/hint instead of CliExecError."""
    set_rules, _ = fake_cli
    set_rules([{"argv_contains": ["+update"], "stdout": {
        "ok": False, "data": {"result": "failed",
                              "warnings": ["degrade_code=1011,no changes"]},
        "error": {"type": "api", "subtype": "degrade",
                  "message": "no document changes", "hint": "check content"}},
        "exit": 1}])
    env = run_lark_cli(["docs", "+update"])
    assert env["ok"] is False
    with pytest.raises(LarkApiError) as exc_info:
        unwrap(env)
    assert exc_info.value.hint == "check content"


def test_run_nonzero_exit_raises_cli_exec(fake_cli):
    set_rules, _ = fake_cli
    set_rules([{"argv_contains": ["boom"], "stdout": "panic: something broke", "exit": 1}])
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
