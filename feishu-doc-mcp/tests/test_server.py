import asyncio
import json

from fastmcp import Client

from feishu_doc_mcp.server import mcp

EXPECTED_TOOLS = {
    "check_environment", "get_doc_info", "read_document",
    "list_comments", "get_comment_thread", "apply_block_operations",
    "reply_comment", "resolve_comment",
}


def _run(coro):
    return asyncio.run(coro)


def _result_payload(result):
    """Extract the tool's returned payload from a CallToolResult."""
    if result.data is not None:
        return result.data
    return json.loads(result.content[0].text)


def test_exactly_seven_tools_registered():
    async def go():
        async with Client(mcp) as client:
            tools = await client.list_tools()
            return {t.name for t in tools}
    assert _run(go()) == EXPECTED_TOOLS


def test_check_environment_via_mcp(fake_cli):
    set_rules, _ = fake_cli
    set_rules([
        {"argv_contains": ["auth", "status"],
         "stdout": {"ok": True, "data": None,
                    "identities": {"user": {"status": "ready"}}}, "exit": 0},
        {"argv_contains": ["auth", "check"],
         "stdout": {"ok": True, "granted": [], "missing": ["docx:document"]},
         "exit": 0},
    ])

    async def go():
        async with Client(mcp) as client:
            r = await client.call_tool("check_environment", {})
            return _result_payload(r)
    payload = _run(go())
    assert payload["logged_in"] is True
    assert payload["missing_scopes"] == ["docx:document"]


def test_lark_error_serialized_with_hint(fake_cli):
    set_rules, _ = fake_cli
    set_rules([{
        "argv_contains": ["api", "POST"],
        "stdout": {"ok": False, "error": {
            "type": "api", "subtype": "permission_denied",
            "message": "no scope", "hint": "run: lark-cli auth login --scope X"}},
        "exit": 0,
    }])

    async def go():
        async with Client(mcp) as client:
            r = await client.call_tool(
                "get_doc_info", {"doc_url": "Z1FjAbCdEf1234"})
            return _result_payload(r)
    payload = _run(go())
    assert payload["error"]["code"] == "permission_denied"
    assert payload["error"]["hint"] == "run: lark-cli auth login --scope X"
    assert set(payload["error"]) == {"code", "message", "lark_code", "hint"}
