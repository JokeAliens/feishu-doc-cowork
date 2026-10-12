import json
import os
import sys

import pytest

from feishu_doc_mcp.scopes import REQUIRED_SCOPES
from feishu_doc_mcp.tools.environment import check_environment

FAKE_BIN = os.path.join(os.path.dirname(__file__), "fake_lark_cli.py")


@pytest.fixture()
def fake_cli(tmp_path, monkeypatch):
    log_path = tmp_path / "calls.jsonl"
    responses_path = tmp_path / "responses.json"
    monkeypatch.setenv("LARK_CLI_BIN", sys.executable)
    monkeypatch.setenv("LARK_CLI_BIN_ARGS", FAKE_BIN)
    monkeypatch.setenv("FAKE_LARK_LOG", str(log_path))
    monkeypatch.setenv("FAKE_LARK_RESPONSES", str(responses_path))

    def set_rules(rules):
        responses_path.write_text(json.dumps(rules, ensure_ascii=False), encoding="utf-8")

    return set_rules


def _status_rule(user_status):
    return {
        "argv_contains": ["auth", "status"],
        "stdout": {
            "ok": True,
            "data": None,
            "identities": {"user": {"status": user_status}},
        },
        "exit": 0,
    }


def _check_rule(granted, missing):
    return {
        "argv_contains": ["auth", "check"],
        "stdout": {"ok": True, "granted": granted, "missing": missing},
        "exit": 0,
    }


def test_all_ready_no_missing(fake_cli):
    set_rules = fake_cli
    set_rules([_status_rule("ready"), _check_rule(REQUIRED_SCOPES, None)])
    r = check_environment()
    assert r["logged_in"] is True
    assert r["missing_scopes"] == []
    assert r["suggested_login_command"] == ""


def test_missing_scopes_builds_precise_login_command(fake_cli):
    set_rules = fake_cli
    missing = ["docx:document", "docs:document.comment:read"]
    granted = [s for s in REQUIRED_SCOPES if s not in missing]
    set_rules([_status_rule("ready"), _check_rule(granted, missing)])
    r = check_environment()
    assert r["logged_in"] is True
    assert sorted(r["missing_scopes"]) == sorted(missing)
    cmd = r["suggested_login_command"]
    assert cmd.startswith("lark-cli auth login")
    for s in missing:
        assert f'--scope "{s}"' in cmd
    for s in granted:
        assert s not in cmd
    assert "--recommend" not in cmd and "--domain" not in cmd


def test_not_logged_in(fake_cli):
    set_rules = fake_cli
    set_rules([_status_rule("missing")])
    r = check_environment()
    assert r["logged_in"] is False
    assert sorted(r["missing_scopes"]) == sorted(REQUIRED_SCOPES)
    for s in REQUIRED_SCOPES:
        assert f'--scope "{s}"' in r["suggested_login_command"]
