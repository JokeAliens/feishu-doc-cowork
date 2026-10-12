"""get_doc_info tool (SPEC §5.2)."""

import json

from ..cli_runner import run_lark_cli, unwrap
from ..errors import LarkApiError
from ..url_parse import LegacyDocError, parse_doc_url

_OWNER_KEYS = ("owner_id", "owner_open_id", "owner")
_TOKEN_KEYS = ("token", "obj_token", "doc_token")


def _first_key(mapping, keys):
    for key in keys:
        value = mapping.get(key)
        if value:
            return value
    return None


def _unwrap_wiki(url):
    """Resolve a wiki node to its real docx token via drive +inspect."""
    data = unwrap(run_lark_cli(["drive", "+inspect", "--url", url]))
    doc_type = data.get("type") or data.get("obj_type")
    token = _first_key(data, _TOKEN_KEYS)
    if not token or not doc_type:
        raise LarkApiError(
            code="inspect_unparseable",
            message=f"drive +inspect response lacks token/type: {json.dumps(data, ensure_ascii=False)[:300]}",
        )
    if doc_type == "doc":
        raise LegacyDocError(token)
    if doc_type != "docx":
        raise LarkApiError(
            code="unsupported_doc_type",
            message=f"wiki 节点解析结果为 {doc_type}，仅支持 docx",
        )
    return token, data.get("title")


def _fetch_meta(doc_token):
    body = {
        "request_docs": [{"doc_token": doc_token, "doc_type": "docx"}],
        "with_url": False,
    }
    data = unwrap(run_lark_cli([
        "api", "POST", "/open-apis/drive/v1/metas/batch_query",
        "--data", json.dumps(body, ensure_ascii=False),
    ]))
    metas = (data or {}).get("metas") or []
    if not metas:
        raise LarkApiError(code="meta_not_found",
                           message=f"metas batch_query 未返回 {doc_token} 的元信息")
    return metas[0]


def get_doc_info(doc_url):
    """Resolve a doc URL/token to {doc_id, doc_type, title, owner_id}."""
    parsed = parse_doc_url(doc_url)
    title = None
    if parsed["doc_type"] == "wiki":
        token, title = _unwrap_wiki(parsed["url"])
    else:
        token = parsed["doc_token"]

    meta = _fetch_meta(token)
    owner_id = _first_key(meta, _OWNER_KEYS)
    if not owner_id:
        raise LarkApiError(
            code="owner_unparseable",
            message=f"metas 响应缺少 owner 字段: {json.dumps(meta, ensure_ascii=False)[:300]}",
        )
    return {
        "doc_id": token,
        "doc_type": "docx",
        "title": meta.get("title") or title or "",
        "owner_id": owner_id,
    }
