import pytest

from feishu_doc_mcp.url_parse import LegacyDocError, parse_doc_url


def test_full_docx_url_with_query():
    r = parse_doc_url("https://xxx.feishu.cn/docx/Z1FjAbCdEf1234?from=xx&bar=1")
    assert r["doc_token"] == "Z1FjAbCdEf1234"
    assert r["doc_type"] == "docx"


def test_bare_token_defaults_docx():
    r = parse_doc_url("Z1FjAbCdEf1234")
    assert r["doc_token"] == "Z1FjAbCdEf1234"
    assert r["doc_type"] == "docx"


def test_wiki_url_marked_wiki():
    r = parse_doc_url("https://xxx.feishu.cn/wiki/WkAbCdEf1234")
    assert r["doc_token"] == "WkAbCdEf1234"
    assert r["doc_type"] == "wiki"


def test_legacy_doc_url_rejected():
    with pytest.raises(LegacyDocError) as exc_info:
        parse_doc_url("https://xxx.feishu.cn/doc/DocAbCdEf1234")
    assert "docx" in str(exc_info.value).lower() or "迁移" in str(exc_info.value)


def test_garbage_input_rejected():
    with pytest.raises(ValueError):
        parse_doc_url("https://xxx.feishu.cn/sheets/abc")
