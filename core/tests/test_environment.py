import json
import os
import sys

import pytest

from cowork_core.scopes import REQUIRED_SCOPES
from cowork_core.tools.environment import check_environment

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
    set_rules, _ = fake_cli
    set_rules([_status_rule("ready"), _check_rule(REQUIRED_SCOPES, None)])
    r = check_environment()
    assert r["logged_in"] is True
    assert r["missing_scopes"] == []
    assert r["suggested_login_command"] == ""


def test_missing_scopes_builds_precise_login_command(fake_cli):
    set_rules, _ = fake_cli
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
    set_rules, _ = fake_cli
    set_rules([_status_rule("missing")])
    r = check_environment()
    assert r["logged_in"] is False
    assert sorted(r["missing_scopes"]) == sorted(REQUIRED_SCOPES)
    for s in REQUIRED_SCOPES:
        assert f'--scope "{s}"' in r["suggested_login_command"]
