import json

import pytest

from feishu_doc_mcp.tools.block_ops import ConflictError, apply_block_operations

DOC = "Z1FjAbCdEf1234"
REV_RULE = {
    "argv_contains": ["docs", "+fetch"],
    "stdout": {"ok": True, "data": {"content": "x", "revision_id": 42}},
    "exit": 0,
}
UPDATE_RULE = {
    "argv_contains": ["docs", "+update"],
    "stdout": {"ok": True, "data": {"revision_id": 43}},
    "exit": 0,
}
BOARD_RULE = {
    "argv_contains": ["whiteboard", "+update"],
    "stdout": {"ok": True, "data": {}},
    "exit": 0,
}
API_RULE = {
    "argv_contains": ["api", "PATCH"],
    "stdout": {"ok": True, "data": {}},
    "exit": 0,
}
ALL_RULES = [REV_RULE, UPDATE_RULE, BOARD_RULE, API_RULE]


def write_calls(all_calls):
    """Real (non-dry-run) write invocations."""
    return [c for c in all_calls
            if any(a in ("+update", "api") for a in c) and "--dry-run" not in c
            and "+fetch" not in c]


def test_update_text_single_write_no_overwrite(fake_cli):
    set_rules, calls = fake_cli
    set_rules(ALL_RULES)
    r = apply_block_operations(DOC, [
        {"type": "update_text", "block_id": "blk002",
         "old_text": "旧句子", "new_text": "新句子"},
    ], expected_revision_id=42)
    writes = write_calls(calls())
    assert len(writes) == 1
    argv = writes[0]
    assert "str_replace" in argv and "blk002" in argv
    assert "--pattern" in argv and "旧句子" in argv
    assert "overwrite" not in argv and "append" not in argv
    assert any(a.startswith("--revision-id=") for a in argv)
    # dry-run preview happened before the real write
    dry = [c for c in calls() if "--dry-run" in c and "+update" in c]
    assert len(dry) == 1
    assert r["results"][0]["status"] == "ok"
    assert r["revision_id"] == 42  # final revision re-fetched


def test_conflict_raises_before_any_write(fake_cli):
    set_rules, calls = fake_cli
    rules = [dict(REV_RULE, stdout={"ok": True, "data": {"content": "x", "revision_id": 99}})]
    set_rules(rules)
    with pytest.raises(ConflictError) as exc_info:
        apply_block_operations(DOC, [
            {"type": "update_text", "block_id": "b", "old_text": "a", "new_text": "b"},
        ], expected_revision_id=42)
    assert exc_info.value.code == "CONFLICT"
    assert write_calls(calls()) == []


def test_overwrite_op_rejected(fake_cli):
    set_rules, calls = fake_cli
    set_rules(ALL_RULES)
    with pytest.raises(ValueError):
        apply_block_operations(DOC, [
            {"type": "overwrite_document", "content": "x"},
        ], expected_revision_id=42)
    assert calls() == []


def test_replace_block_single_write(fake_cli):
    set_rules, calls = fake_cli
    set_rules(ALL_RULES)
    apply_block_operations(DOC, [
        {"type": "replace_block", "block_id": "blk005",
         "content_xml": "<p>替换内容</p>"},
    ], expected_revision_id=42)
    writes = write_calls(calls())
    assert len(writes) == 1
    assert "block_replace" in writes[0] and "blk005" in writes[0]


def test_table_cells_expand_one_write_per_cell(fake_cli):
    set_rules, calls = fake_cli
    set_rules(ALL_RULES)
    apply_block_operations(DOC, [
        {"type": "update_table_cells", "cells": [
            {"block_id": "cellA", "content_xml": "<p>1</p>"},
            {"block_id": "cellB", "content_xml": "<p>2</p>"},
        ]},
    ], expected_revision_id=42)
    writes = write_calls(calls())
    assert len(writes) == 2
    assert all("block_replace" in w for w in writes)


def test_table_insert_rows_uses_raw_api_patch(fake_cli):
    set_rules, calls = fake_cli
    set_rules(ALL_RULES)
    apply_block_operations(DOC, [
        {"type": "table_insert_rows", "table_block_id": "tbl1",
         "row_index": 2, "count": 3},
    ], expected_revision_id=42)
    writes = write_calls(calls())
    assert len(writes) == 1
    argv = writes[0]
    assert "api" in argv and "PATCH" in argv
    assert f"/open-apis/docx/v1/documents/{DOC}/blocks/tbl1" in argv
    data = argv[argv.index("--data") + 1]
    assert "insert_table_row" in data


def test_update_board_uses_whiteboard_without_overwrite(fake_cli):
    set_rules, calls = fake_cli
    set_rules(ALL_RULES)
    apply_block_operations(DOC, [
        {"type": "update_board", "whiteboard_token": "wb1",
         "dsl": "graph TD; A-->B"},
    ], expected_revision_id=42)
    writes = write_calls(calls())
    assert len(writes) == 1
    argv = writes[0]
    assert "whiteboard" in argv and "+update" in argv
    assert "wb1" in argv
    assert "--overwrite" not in argv


def test_board_unsupported_marked_not_raised(fake_cli):
    set_rules, calls = fake_cli
    rules = [r for r in ALL_RULES if r is not BOARD_RULE] + [
        dict(BOARD_RULE, stdout={"ok": False, "error": {
            "type": "api", "subtype": "invalid_param",
            "message": "unsupported node", "hint": None}}),
    ]
    set_rules(rules)
    r = apply_block_operations(DOC, [
        {"type": "update_board", "whiteboard_token": "wb1", "dsl": "x"},
    ], expected_revision_id=42)
    assert r["results"][0]["status"] == "BOARD_UNSUPPORTED"
