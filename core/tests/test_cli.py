"""Tests for the cowork CLI (replaces the removed MCP layer)."""

import json

import pytest

from cowork_core.cli import main


def test_cli_check_environment_ok(fake_cli, capsys):
    set_rules, _ = fake_cli
    set_rules([
        {"argv_contains": ["auth", "status"],
         "stdout": {"ok": True, "identities": {"user": {"status": "ready"}}},
         "exit": 0},
        {"argv_contains": ["auth", "check"],
         "stdout": {"ok": True, "granted": [], "missing": None}, "exit": 0},
    ])
    rc = main(["check-environment"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["logged_in"] is True
    assert out["missing_scopes"] == []


def test_cli_error_exit1_with_hint(fake_cli, capsys):
    """LarkApiError -> error JSON on stdout, exit 1, hint preserved."""
    set_rules, _ = fake_cli
    set_rules([{
        "argv_contains": ["api", "POST"],
        "stdout": {"ok": False, "error": {
            "type": "api", "subtype": "permission_denied",
            "message": "no scope", "hint": "run: lark-cli auth login --scope X"}},
        "exit": 0,
    }])
    rc = main(["get-doc-info", "Z1FjAbCdEf1234"])
    assert rc == 1
    out = json.loads(capsys.readouterr().out)
    assert out["error"]["code"] == "permission_denied"
    assert out["error"]["hint"] == "run: lark-cli auth login --scope X"


def test_cli_apply_ops_from_file(fake_cli, capsys, tmp_path):
    set_rules, calls = fake_cli
    ops_file = tmp_path / "ops.json"
    ops_file.write_text(json.dumps([
        {"type": "update_text", "block_id": "b1", "old_text": "a", "new_text": "b"},
    ]), encoding="utf-8")
    set_rules([
        {"argv_contains": ["docs", "+fetch"],
         "stdout": {"ok": True, "data": {"content": "x", "revision_id": 42}},
         "exit": 0},
        {"argv_contains": ["+update"],
         "stdout": {"ok": True, "data": {"revision_id": 43}}, "exit": 0},
    ])
    rc = main(["apply-ops", "DOC1", "--ops", f"@{ops_file}",
               "--expected-revision", "42"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["results"][0]["status"] == "ok"
    writes = [c for c in calls() if "+update" in c and "--dry-run" not in c]
    assert len(writes) == 1


def test_cli_apply_ops_conflict_exit1(fake_cli, capsys):
    set_rules, _ = fake_cli
    set_rules([{
        "argv_contains": ["docs", "+fetch"],
        "stdout": {"ok": True, "data": {"content": "x", "revision_id": 99}},
        "exit": 0,
    }])
    rc = main(["apply-ops", "DOC1", "--ops", "[]", "--expected-revision", "42"])
    assert rc == 1
    out = json.loads(capsys.readouterr().out)
    assert out["error"]["code"] == "CONFLICT"


def test_cli_resolve_and_reply(fake_cli, capsys):
    set_rules, calls = fake_cli
    set_rules([
        {"argv_contains": ["+resolve-comment"],
         "stdout": {"ok": True, "data": {"is_solved": True}}, "exit": 0},
        {"argv_contains": ["+add-reply"],
         "stdout": {"ok": True, "data": {"reply_id": "r1"}}, "exit": 0},
    ])
    assert main(["resolve", "DOC1", "c_1"]) == 0
    assert main(["reply", "DOC1", "c_1", "修改完成"]) == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert json.loads(out[0])["is_solved"] is True
    assert json.loads(out[1])["reply_id"] == "r1"
