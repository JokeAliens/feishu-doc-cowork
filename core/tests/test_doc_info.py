import json
import os
import sys

import pytest

from cowork_core.tools.doc_info import get_doc_info

META_RULE = {
    "argv_contains": ["api", "POST", "/open-apis/drive/v1/metas/batch_query"],
    "stdout": {
        "ok": True,
        "data": {"metas": [{"doc_token": "Z1FjAbCdEf1234", "doc_type": "docx",
                             "title": "测试文档", "owner_id": "ou_owner123"}]},
    },
    "exit": 0,
}


def test_docx_url_returns_info(fake_cli):
    set_rules, calls = fake_cli
    set_rules([META_RULE])
    r = get_doc_info("https://xxx.feishu.cn/docx/Z1FjAbCdEf1234?x=1")
    assert r == {"doc_id": "Z1FjAbCdEf1234", "doc_type": "docx",
                 "title": "测试文档", "owner_id": "ou_owner123"}
    # metas request body must reference the token
    api_call = [c for c in calls() if any("batch_query" in a for a in c)][0]
    data_arg = api_call[api_call.index("--data") + 1]
    assert "Z1FjAbCdEf1234" in data_arg


def test_wiki_url_unwrapped_via_inspect(fake_cli):
    set_rules, calls = fake_cli
    set_rules([
        {
            "argv_contains": ["drive", "+inspect"],
            "stdout": {"ok": True, "data": {"type": "docx", "title": "wiki文档",
                                            "token": "Z1FjRealDocx"}},
            "exit": 0,
        },
        {
            "argv_contains": ["api", "POST"],
            "stdout": {"ok": True, "data": {"metas": [{"doc_token": "Z1FjRealDocx",
                       "doc_type": "docx", "title": "wiki文档", "owner_id": "ou_owner9"}]}},
            "exit": 0,
        },
    ])
    r = get_doc_info("https://xxx.feishu.cn/wiki/WkAbCdEf1234")
    assert r["doc_id"] == "Z1FjRealDocx"
    assert r["doc_type"] == "docx"
    assert r["owner_id"] == "ou_owner9"
    assert any("+inspect" in " ".join(c) for c in calls())


def test_owner_id_candidate_key(fake_cli):
    """metas payload using an alternative owner key still resolves."""
    set_rules, _ = fake_cli
    rule = dict(META_RULE)
    rule["stdout"] = {"ok": True, "data": {"metas": [{"doc_token": "Z1FjAbCdEf1234",
                      "doc_type": "docx", "title": "t", "owner_open_id": "ou_alt"}]}}
    set_rules([rule])
    r = get_doc_info("Z1FjAbCdEf1234")
    assert r["owner_id"] == "ou_alt"
