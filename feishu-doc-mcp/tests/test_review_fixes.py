"""Regression tests locking the final-review fixes (RED first)."""

import json

import pytest

from feishu_doc_mcp.block_map import parse_fetch_output
from feishu_doc_mcp.errors import LarkApiError
from feishu_doc_mcp.tools.block_ops import (
    PartialApplyError, apply_block_operations,
)
from test_block_ops import API_RULE, BOARD_RULE, DOC, REV_RULE, UPDATE_RULE

UPD_RULE_43 = dict(UPDATE_RULE)  # write response carries the new revision


def test_revision_chained_across_batch(fake_cli):
    """Important #1: every +update write carries --revision-id, chained from
    the previous write's response revision."""
    set_rules, calls = fake_cli
    set_rules([REV_RULE, UPD_RULE_43, BOARD_RULE, API_RULE])
    apply_block_operations(DOC, [
        {"type": "update_text", "block_id": "b1", "old_text": "a", "new_text": "b"},
        {"type": "update_text", "block_id": "b2", "old_text": "c", "new_text": "d"},
    ], expected_revision_id=42)
    writes = [c for c in calls()
              if "+update" in c and "--dry-run" not in c and "+fetch" not in c]
    assert len(writes) == 2
    rev_of = lambda argv: argv[argv.index("--revision-id") + 1]
    assert rev_of(writes[0]) == "42"
    assert rev_of(writes[1]) == "43"  # chained from first write's response


def test_revision_id_on_all_update_commands(fake_cli):
    """Important #1: block_delete/block_insert_after also carry --revision-id."""
    set_rules, calls = fake_cli
    set_rules([REV_RULE, UPD_RULE_43, BOARD_RULE, API_RULE])
    apply_block_operations(DOC, [
        {"type": "delete_blocks", "block_id": "b9"},
    ], expected_revision_id=42)
    write = [c for c in calls()
             if "+update" in c and "--dry-run" not in c][0]
    assert "--revision-id" in write


def test_revision_string_normalized_no_false_conflict(fake_cli):
    """Minor #3 (absorbed): lark-cli returning revision as string must not
    cause a false CONFLICT."""
    set_rules, calls = fake_cli
    rules = [dict(REV_RULE, stdout={"ok": True, "data": {"content": "x",
                                                         "revision_id": "42"}}),
             UPD_RULE_43, BOARD_RULE, API_RULE]
    set_rules(rules)
    r = apply_block_operations(DOC, [
        {"type": "update_text", "block_id": "b1", "old_text": "a", "new_text": "b"},
    ], expected_revision_id=42)
    assert r["results"][0]["status"] == "ok"


def test_partial_failure_reports_applied_ops(fake_cli):
    """Important #2: mid-batch failure surfaces which ops were applied."""
    set_rules, _ = fake_cli
    fail_update = dict(UPDATE_RULE, stdout={"ok": False, "error": {
        "type": "api", "subtype": "internal", "message": "boom", "hint": None}})
    # first write ok, second fails: order rules so +update with b2 fails
    rules = [
        REV_RULE,
        {"argv_contains": ["+update", "--block-id", "b2"],
         "stdout": fail_update["stdout"], "exit": 0},
        {"argv_contains": ["+update"],
         "stdout": {"ok": True, "data": {"revision_id": 43}}, "exit": 0},
        BOARD_RULE, API_RULE,
    ]
    set_rules(rules)
    with pytest.raises(PartialApplyError) as exc_info:
        apply_block_operations(DOC, [
            {"type": "update_text", "block_id": "b1", "old_text": "a", "new_text": "b"},
            {"type": "update_text", "block_id": "b2", "old_text": "c", "new_text": "d"},
        ], expected_revision_id=42)
    err = exc_info.value
    assert err.applied == ["b1"]
    assert "b1" in err.message and "b2" in err.message


def test_nonempty_content_without_markers_raises():
    """Important #5: unparseable format must fail loudly, not silently
    return an empty block_map."""
    with pytest.raises(LarkApiError) as exc_info:
        parse_fetch_output({"document": {"content": "<p>第一段没有记号</p><p>第二段也没有</p>",
                                         "revision_id": 1}})
    assert exc_info.value.code == "block_map_unresolved"
    assert "第一段没有记号" in exc_info.value.message  # sample included


def test_empty_document_allowed():
    r = parse_fetch_output({"document": {"content": "", "revision_id": 1}})
    assert r["block_map"] == []


def test_missing_revision_raises():
    """Minor #9 (absorbed): missing revision fails at parse time."""
    with pytest.raises(ValueError):
        parse_fetch_output({"document": {"content": "<p id='doxcnX1'>x</p>"}})
