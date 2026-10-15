"""Comment tools: list_comments / get_comment_thread / reply_comment (SPEC §5.4–5.7)."""

import json

from ..cli_runner import run_lark_cli, unwrap
from ..errors import LarkApiError


def _text_from_elements(content):
    """Flatten a comment/reply content structure to plain text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    elements = content.get("elements") or []
    parts = []
    for el in elements:
        run = el.get("text_run") or {}
        parts.append(run.get("text", ""))
    return "".join(parts)


def _to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _normalize_comment(item):
    # real API shape (calibrated 2026-10-12): the comment body is
    # reply_list.replies[0]; no top-level content/reply_count fields.
    replies = (item.get("reply_list") or {}).get("replies") or []
    # reply order is not guaranteed (observed live 2026-10-12);
    # the comment body is the chronologically first reply.
    first = min(replies, key=lambda r: _to_int(r.get("create_time"))) if replies else {}
    return {
        "comment_id": item.get("comment_id"),
        "user_id": item.get("user_id") or first.get("user_id"),
        "create_time": _to_int(item.get("create_time") or first.get("create_time")),
        "update_time": _to_int(item.get("update_time") or first.get("update_time")),
        "content": _text_from_elements(item.get("content") or first.get("content")),
        "quote": item.get("quote") or "",
        "reply_count": max(len(replies) - 1, 0),
        # all participant ids (incl. comment author): lets the poll layer
        # treat a comment as owner-endorsed when the owner replied (v1.0.4)
        "replier_ids": [r.get("user_id") for r in replies if r.get("user_id")],
        "is_solved": bool(item.get("is_solved")),
        "is_whole": bool(item.get("is_whole")),
    }


def _normalize_reply(item):
    return {
        "reply_id": item.get("reply_id"),
        "user_id": item.get("user_id"),
        "create_time": _to_int(item.get("create_time")),
        "update_time": _to_int(item.get("update_time")),
        "content": _text_from_elements(item.get("content")),
    }


def list_comments(doc_id, is_solved=False):
    """List comments oldest-first, paginating via --page-token."""
    solved = "true" if is_solved else "false"
    argv = ["drive", "+list-comments", "--url", doc_id,
            "--type", "docx", "--solved-status", solved]
    items = []
    page_token = None
    while True:
        page_argv = list(argv)
        if page_token:
            page_argv += ["--page-token", page_token]
        data = unwrap(run_lark_cli(page_argv))
        items.extend(data.get("items") or [])
        if not data.get("has_more"):
            break
        page_token = data.get("page_token")
        if not page_token:
            break
    return sorted((_normalize_comment(i) for i in items),
                  key=lambda c: c["create_time"])


def get_comment_thread(doc_id, comment_id):
    """Fetch the comment plus all its replies (SPEC §5.5)."""
    data = unwrap(run_lark_cli([
        "api", "POST",
        f"/open-apis/drive/v1/files/{doc_id}/comments/batch_query",
        "--params", json.dumps({"file_type": "docx"}),
        "--data", json.dumps({"comment_ids": [comment_id]}),
    ]))
    items = data.get("items") or []
    if not items:
        raise LarkApiError(code="comment_not_found",
                           message=f"评论 {comment_id} 不存在或已删除")
    comment = _normalize_comment(items[0])

    replies_data = unwrap(run_lark_cli([
        "drive", "+list-replies", "--url", doc_id,
        "--type", "docx", "--comment-id", comment_id,
    ]))
    replies = [_normalize_reply(r) for r in (replies_data.get("items") or [])]
    return {"comment": comment, "replies": replies}


def resolve_comment(doc_id, comment_id):
    """Mark a comment solved (resolve & hide). Solved comments disappear
    from the default poll (is_solved=false), closing the loop."""
    return unwrap(run_lark_cli([
        "drive", "+resolve-comment", "--url", doc_id,
        "--type", "docx", "--comment-id", comment_id,
    ]))


def reply_comment(doc_id, comment_id, content):
    """Reply to a comment as the authorized user (SPEC §5.7)."""
    reply_elements = json.dumps([{"type": "text", "text": content}],
                                ensure_ascii=False)
    try:
        return unwrap(run_lark_cli([
            "drive", "+add-reply", "--url", doc_id,
            "--type", "docx", "--comment-id", comment_id,
            "--content", reply_elements,
        ]))
    except LarkApiError as e:
        msg = (e.message or "").lower()
        if "solved" in msg or "whole" in msg:
            raise LarkApiError(code="reply_not_allowed",
                               message=e.message, hint=e.hint,
                               lark_code=e.lark_code) from e
        raise
