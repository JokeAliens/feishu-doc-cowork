"""FastMCP server assembly for feishu-doc-mcp (SPEC §5).

Thin wrapper: one MCP tool -> one or a few lark-cli calls. No state, no
business logic, no intent judgement. Errors are serialized as
{"error": {"code", "message", "lark_code", "hint"}} instead of raising.

Deliberately NOT provided (SPEC §5.8): full-document replace, git tools,
unrelated lark-cli domains (im/calendar/mail/...).
"""

from functools import wraps

from fastmcp import FastMCP

from .errors import CliExecError, LarkApiError
from .tools.block_ops import apply_block_operations as _apply_block_operations
from .tools.comments import (
    get_comment_thread as _get_comment_thread,
    list_comments as _list_comments,
    reply_comment as _reply_comment,
)
from .tools.doc_info import get_doc_info as _get_doc_info
from .tools.environment import check_environment as _check_environment
from .tools.read_doc import read_document as _read_document

mcp = FastMCP("feishu-doc-mcp")


def _serialize_errors(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except LarkApiError as e:
            return e.to_dict()
        except CliExecError as e:
            return {"error": {"code": "cli_exec", "message": str(e),
                              "lark_code": None, "hint": None}}
    return wrapper


@mcp.tool(name="check_environment")
def check_environment() -> dict:
    """检查 lark-cli 登录状态与最小 scope 覆盖（SPEC §5.1）。"""
    return _serialize_errors(_check_environment)()


@mcp.tool(name="get_doc_info")
def get_doc_info(doc_url: str) -> dict:
    """解析文档 URL/token，返回 {doc_id, doc_type, title, owner_id}（SPEC §5.2）。"""
    return _serialize_errors(_get_doc_info)(doc_url)


@mcp.tool(name="read_document")
def read_document(doc_id: str) -> dict:
    """读取全文档：markdown + block_map + revision_id，可逆寻址（SPEC §5.3）。"""
    return _serialize_errors(_read_document)(doc_id)


@mcp.tool(name="list_comments")
def list_comments(doc_id: str, is_solved: bool = False) -> list:
    """列出文档评论，按 create_time 升序（SPEC §5.4）。"""
    return _serialize_errors(_list_comments)(doc_id, is_solved)


@mcp.tool(name="get_comment_thread")
def get_comment_thread(doc_id: str, comment_id: str) -> dict:
    """拉取评论完整线程（评论 + 全部回复）（SPEC §5.5）。"""
    return _serialize_errors(_get_comment_thread)(doc_id, comment_id)


@mcp.tool(name="apply_block_operations")
def apply_block_operations(doc_id: str, operations: list,
                           expected_revision_id: int) -> dict:
    """按序执行块级最小修改，带 revision 冲突检测（SPEC §5.6, §8）。禁止全量覆盖。"""
    return _serialize_errors(_apply_block_operations)(
        doc_id, operations, expected_revision_id)


@mcp.tool(name="reply_comment")
def reply_comment(doc_id: str, comment_id: str, content: str) -> dict:
    """以用户身份回复评论（SPEC §5.7）。"""
    return _serialize_errors(_reply_comment)(doc_id, comment_id, content)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
