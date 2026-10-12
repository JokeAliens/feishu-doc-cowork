"""Shared fixtures: fake lark-cli binary driven by env vars."""

import json
import os
import sys

import pytest

FAKE_BIN = os.path.join(os.path.dirname(__file__), "fake_lark_cli.py")


@pytest.fixture()
def fake_cli(tmp_path, monkeypatch):
    """Point the runner at the fake binary; return (set_rules, calls)."""
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
