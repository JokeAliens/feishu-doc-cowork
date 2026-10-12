import json

import pytest

from cowork_core.block_map import parse_fetch_output
from cowork_core.errors import LarkApiError
from cowork_core.tools.read_doc import read_document

# Real-format fixture calibrated from live fetch 2026-10-12
# (docs +fetch --doc-format xml --detail with-ids, ruijie wiki doc).
CANNED_XML = (
    '<title id="docTokenT">测试文档标题</title>'
    '<p id="doxcnP1" align="center"><b>加粗段落</b></p>'
    '<p id="doxcnP2"></p>'
    '<h1 id="doxcnH1" seq="1" seq-level="auto" seq-marker="1.">问题定义</h1>'
    '<ul><li id="doxcnL1">第一层<ul><li id="doxcnL2">第二层</li></ul></li></ul>'
    '<table id="doxcnT1"><colgroup><col width="96"/><col width="479"/></colgroup>'
    '<tbody>'
    '<tr><td><p id="doxcnC1"><b>主送对象</b></p></td><td><p id="doxcnC2">陈志超</p></td></tr>'
    '<tr><td><p id="doxcnC3">抄送对象</p></td><td><p id="doxcnC4"></p></td></tr>'
    '</tbody></table>'
    '<whiteboard id="doxcnW1" token="GRouw98sphPxknbb9Pqc8NUJn6f"></whiteboard>'
    '<code id="doxcnCode1">name: TZ<br/>  value: x</code>'
)

CANNED_DATA = {"document": {"content": CANNED_XML, "revision_id": 6102,
                            "document_id": "docTokenT"}}


def test_parse_produces_markdown_and_reversible_map():
    r = parse_fetch_output(CANNED_DATA)
    md = r["markdown"].splitlines()
    assert md[0] == "# 测试文档标题"
    assert md[1] == "加粗段落"
    assert md[2] == ""                      # empty paragraph stays a blank line
    assert md[3] == "# 问题定义"
    assert md[4] == "- 第一层"
    assert md[5] == "  - 第二层"
    assert md[6] == "| 主送对象 | 陈志超 |"
    assert md[7] == "| 抄送对象 |  |"
    assert md[8] == "[whiteboard token=GRouw98sphPxknbb9Pqc8NUJn6f]"
    # code fenced
    assert md[9] == "```"
    assert md[10] == "name: TZ"
    assert md[11] == "  value: x"
    assert md[12] == "```"

    by_id = {e["block_id"]: e for e in r["block_map"]}
    # U2-style reverse lookups
    assert by_id["doxcnH1"]["line"] == 4
    assert by_id["doxcnP2"]["line"] == 3
    assert by_id["doxcnL1"]["line"] == 5
    # nesting metadata now real
    assert by_id["doxcnL2"]["parent_id"] == "doxcnL1"
    assert by_id["doxcnL2"]["child_index"] == 0
    assert by_id["doxcnT1"]["block_type"] == "table"
    assert by_id["doxcnC1"]["parent_id"] == "doxcnT1"
    assert by_id["doxcnC1"]["child_index"] == 0
    assert by_id["doxcnC2"]["child_index"] == 1
    assert by_id["doxcnC3"]["child_index"] == 2
    # whiteboard exposes its real token for +update
    wb = by_id["doxcnW1"]
    assert wb["block_type"] == "whiteboard"
    assert wb["whiteboard_token"] == "GRouw98sphPxknbb9Pqc8NUJn6f"
    assert by_id["doxcnCode1"]["block_type"] == "code"


def test_parse_nested_document_envelope_revision():
    assert parse_fetch_output(CANNED_DATA)["revision_id"] == 6102


def test_parse_rejects_payload_without_content():
    with pytest.raises(ValueError):
        parse_fetch_output({"document": {"revision_id": 1}})


def test_parse_rejects_content_without_any_ids():
    with pytest.raises(LarkApiError) as exc_info:
        parse_fetch_output({"document": {"content": "<p>没有 id 的段落</p>",
                                         "revision_id": 1}})
    assert exc_info.value.code == "block_map_unresolved"


def test_empty_document_allowed():
    r = parse_fetch_output({"document": {"content": "", "revision_id": 1}})
    assert r["block_map"] == []


def test_read_document_invokes_xml_with_ids(fake_cli):
    set_rules, calls = fake_cli
    set_rules([{
        "argv_contains": ["docs", "+fetch"],
        "stdout": {"ok": True, "data": CANNED_DATA},
        "exit": 0,
    }])
    r = read_document("HMSvdQCfboayYNxCyjPcY5TfnsM")
    assert r["revision_id"] == 6102
    assert len(r["block_map"]) == 13
    argv = calls()[0]
    for expected in ("+fetch", "--doc-format", "xml", "--detail", "with-ids"):
        assert expected in argv
