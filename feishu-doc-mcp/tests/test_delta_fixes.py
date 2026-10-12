"""Delta-review fix tests (RED first)."""

import pytest

from feishu_doc_mcp.block_map import parse_fetch_output
from test_block_ops import ALL_RULES, DOC, write_calls
from test_read_doc import CANNED_DATA
from feishu_doc_mcp.tools.block_ops import apply_block_operations


def test_table_cells_carry_row_and_col_index():
    """Delta Important #1: cell entries expose row_index/col_index;
    child_index documented as flat id-order."""
    r = parse_fetch_output(CANNED_DATA)
    by_id = {e["block_id"]: e for e in r["block_map"]}
    assert (by_id["doxcnC1"]["row_index"], by_id["doxcnC1"]["col_index"]) == (0, 0)
    assert (by_id["doxcnC2"]["row_index"], by_id["doxcnC2"]["col_index"]) == (0, 1)
    assert (by_id["doxcnC3"]["row_index"], by_id["doxcnC3"]["col_index"]) == (1, 0)
    assert (by_id["doxcnC4"]["row_index"], by_id["doxcnC4"]["col_index"]) == (1, 1)


def test_unknown_tag_descendants_stay_addressable():
    """Delta Important #2: id-bearing descendants of an unknown container
    (e.g. callout) must appear in block_map pointing at the raw line, and
    the raw passthrough must not leak id= attributes into markdown."""
    xml = ('<title id="docT">t</title>'
           '<callout id="doxcnCal1"><p id="doxcnInner1">容器内段落</p></callout>')
    r = parse_fetch_output({"document": {"content": xml, "revision_id": 1}})
    by_id = {e["block_id"]: e for e in r["block_map"]}
    assert "doxcnInner1" in by_id
    assert by_id["doxcnInner1"]["parent_id"] == "doxcnCal1"
    assert 'id="' not in r["markdown"]  # no id leakage


def test_revision_minus_one_uses_glued_flag_form(fake_cli):
    """Delta Important #3: when a write response lacks a revision, the next
    write must pass --revision-id=-1 (glued) so argparse never sees a bare
    -1 token."""
    set_rules, calls = fake_cli
    rules = [
        {"argv_contains": ["docs", "+fetch"],
         "stdout": {"ok": True, "data": {"content": "x", "revision_id": 42}},
         "exit": 0},
        # first write responds WITHOUT revision -> next must use -1
        {"argv_contains": ["+update", "--block-id", "b1"],
         "stdout": {"ok": True, "data": {}}, "exit": 0},
        {"argv_contains": ["+update"],
         "stdout": {"ok": True, "data": {"revision_id": 44}}, "exit": 0},
    ]
    set_rules(rules)
    apply_block_operations(DOC, [
        {"type": "update_text", "block_id": "b1", "old_text": "a", "new_text": "b"},
        {"type": "update_text", "block_id": "b2", "old_text": "c", "new_text": "d"},
    ], expected_revision_id=42)
    writes = write_calls(calls())
    assert "--revision-id=-1" in writes[1]
    assert "--revision-id" not in writes[1]  # glued, not separate token
