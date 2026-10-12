import json
import os
import sys

import pytest

from feishu_doc_mcp.block_map import parse_fetch_output
from feishu_doc_mcp.tools.read_doc import read_document

FAKE_BIN = os.path.join(os.path.dirname(__file__), "fake_lark_cli.py")

# Canned +fetch --detail with-ids payload: two marker styles.
CANNED_MD = "\n".join([
    "# 项目方案 <!-- block_id: blk001 -->",
    "",
    "第一段文字。 <!-- block_id: blk002 -->",
    "第二段文字。 <!-- block_id: blk003 -->",
    "",
    "## 第二章 <!-- block_id: blk004 -->",
    "要点A <!-- block_id: blk005 -->",
    "- 列表项1 <!-- block_id: blk006 -->",
    "- 列表项2 <!-- block_id: blk007 -->",
    "---",
    "blk008 表格说明行",
    "结尾段落。 <!-- block_id: blk009 -->",
    "附注。 <!-- block_id: blk010 -->",
])

CANNED_DATA = {"content": CANNED_MD, "revision_id": 42}


def test_parse_builds_reversible_block_map():
    r = parse_fetch_output(CANNED_DATA)
    entries = r["block_map"]
    assert len(entries) == 10
    md_lines = r["markdown"].splitlines()
    # markers stripped from returned markdown
    assert "block_id" not in r["markdown"]
    # every entry's line number points at the content that carried the marker
    for e in entries:
        assert 1 <= e["line"] <= len(md_lines)
    by_id = {e["block_id"]: e for e in entries}
    # random-sample reverse lookups (U2 style)
    assert md_lines[by_id["blk001"]["line"] - 1] == "# 项目方案"
    assert md_lines[by_id["blk007"]["line"] - 1] == "- 列表项2"
    assert md_lines[by_id["blk010"]["line"] - 1] == "附注。"
    # prefix-style marker also parsed
    assert "blk008" in by_id
    # non-block lines produce no entries
    ids = set(by_id)
    assert all(not e["block_id"].startswith("---") for e in entries)
    assert len(ids) == 10


def test_parse_extracts_revision_id():
    assert parse_fetch_output(CANNED_DATA)["revision_id"] == 42


def test_parse_rejects_payload_without_content():
    with pytest.raises(ValueError):
        parse_fetch_output({"revision_id": 1})


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

    def calls():
        if not log_path.exists():
            return []
        return [json.loads(line)["argv"] for line in log_path.read_text().splitlines()]

    return set_rules, calls


def test_read_document_invokes_fetch_with_ids(fake_cli):
    set_rules, calls = fake_cli
    set_rules([{
        "argv_contains": ["docs", "+fetch"],
        "stdout": {"ok": True, "data": CANNED_DATA},
        "exit": 0,
    }])
    r = read_document("Z1FjAbCdEf1234")
    assert r["revision_id"] == 42
    assert len(r["block_map"]) == 10
    argv = calls()[0]
    for expected in ("+fetch", "--doc", "Z1FjAbCdEf1234", "--doc-format", "markdown",
                     "--detail", "with-ids"):
        assert expected in argv
