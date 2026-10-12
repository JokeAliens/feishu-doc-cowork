import json

import pytest

from feishu_doc_mcp.errors import LarkApiError
from feishu_doc_mcp.tools.comments import (
    get_comment_thread, list_comments, reply_comment,
)

DOC = "Z1FjAbCdEf1234"


def _comment(cid, user, ctime, utime, text, quote="", replies=0):
    # real shape (calibrated 2026-10-12): comment body lives in
    # reply_list.replies[0]; no top-level content/reply_count fields.
    reply_list = [{"content": {"elements": [{"type": "text_run",
                                             "text_run": {"text": text}}]},
                   "reply_id": f"{cid}_r0", "user_id": user,
                   "create_time": ctime, "update_time": utime}]
    for i in range(replies):
        reply_list.append({"content": {"elements": [{"type": "text_run",
                           "text_run": {"text": f"回复{i}"}}]},
                           "reply_id": f"{cid}_r{i+1}", "user_id": user,
                           "create_time": ctime + i + 1, "update_time": ctime + i + 1})
    return {
        "comment_id": cid, "user_id": user,
        "create_time": ctime, "update_time": utime,
        "reply_list": {"replies": reply_list},
        "quote": quote,
        "is_solved": False, "is_whole": False,
    }


PAGE1 = {
    "argv_contains": ["drive", "+list-comments"],
    "stdout": {"ok": True, "data": {
        "items": [_comment("c_2", "ou_owner", 200, 200, "第二条"),
                  _comment("c_1", "ou_owner", 100, 100, "第一条", quote="原文")],
        "has_more": True, "page_token": "tok1"}},
    "exit": 0,
}
PAGE2 = {
    "argv_contains": ["drive", "+list-comments", "--page-token", "tok1"],
    "stdout": {"ok": True, "data": {
        "items": [_comment("c_3", "ou_other", 300, 300, "第三条")],
        "has_more": False}},
    "exit": 0,
}


def test_comment_body_is_earliest_reply_regardless_of_order():
    """reply_list order is not guaranteed; body = earliest reply."""
    item = _comment("c_9", "ou_x", 100, 200, "评论正文")
    # shuffle: put the follow-up reply first
    replies = item["reply_list"]["replies"]
    item["reply_list"]["replies"] = list(reversed(replies)) if len(replies) > 1 else replies
    item2 = _comment("c_9", "ou_x", 100, 200, "评论正文", replies=1)
    item2["reply_list"]["replies"] = list(reversed(item2["reply_list"]["replies"]))
    from feishu_doc_mcp.tools.comments import _normalize_comment
    n = _normalize_comment(item2)
    assert n["content"] == "评论正文"
    assert n["reply_count"] == 1


def test_list_comments_paginates_and_normalizes(fake_cli):
    set_rules, calls = fake_cli
    # more specific page-2 rule first (first match wins)
    set_rules([PAGE2, PAGE1])
    comments = list_comments(DOC)
    assert [c["comment_id"] for c in comments] == ["c_1", "c_2", "c_3"]
    c1 = comments[0]
    assert c1["user_id"] == "ou_owner"
    assert c1["content"] == "第一条"
    assert c1["quote"] == "原文"
    assert c1["create_time"] == 100 and c1["update_time"] == 100
    assert c1["reply_count"] == 0
    # page-token continuation happened
    p2 = [c for c in calls() if "--page-token" in c]
    assert len(p2) == 1 and "tok1" in p2[0]
    # default is_solved=false maps to --solved-status false
    first = calls()[0]
    assert "--solved-status" in first and "false" in first


THREAD_RULES = [
    {
        "argv_contains": ["api", "POST"],
        "stdout": {"ok": True, "data": {
            "items": [_comment("c_1", "ou_owner", 100, 150, "改成三分离")]}},
        "exit": 0,
    },
    {
        "argv_contains": ["drive", "+list-replies"],
        "stdout": {"ok": True, "data": {"items": [
            {"reply_id": "r_1", "user_id": "ou_owner",
             "create_time": "120", "update_time": "120",
             "content": {"elements": [{"type": "text_run", "text_run": {"text": "补充：含画板"}}]}},
        ]}},
        "exit": 0,
    },
]


def test_get_comment_thread(fake_cli):
    set_rules, _ = fake_cli
    set_rules(THREAD_RULES)
    t = get_comment_thread(DOC, "c_1")
    assert t["comment"]["comment_id"] == "c_1"
    assert t["comment"]["update_time"] == 150
    assert len(t["replies"]) == 1
    assert t["replies"][0]["content"] == "补充：含画板"


def test_reply_comment_content_json(fake_cli):
    set_rules, calls = fake_cli
    set_rules([{
        "argv_contains": ["drive", "+add-reply"],
        "stdout": {"ok": True, "data": {"reply_id": "r_9"}},
        "exit": 0,
    }])
    reply_comment(DOC, "c_1", "修改完成，使用AI模型：GLM5.3， Agent：OMP")
    argv = calls()[0]
    content = json.loads(argv[argv.index("--content") + 1])
    assert content == [{"type": "text",
                        "text": "修改完成，使用AI模型：GLM5.3， Agent：OMP"}]
    assert "c_1" in argv


def test_resolve_comment(fake_cli):
    set_rules, calls = fake_cli
    set_rules([{
        "argv_contains": ["drive", "+resolve-comment"],
        "stdout": {"ok": True, "data": {"is_solved": True}},
        "exit": 0,
    }])
    from feishu_doc_mcp.tools.comments import resolve_comment
    r = resolve_comment(DOC, "c_1")
    assert r["is_solved"] is True
    argv = calls()[0]
    assert "+resolve-comment" in argv and "c_1" in argv


def test_reply_to_solved_comment_maps_error(fake_cli):
    set_rules, _ = fake_cli
    set_rules([{
        "argv_contains": ["drive", "+add-reply"],
        "stdout": {"ok": False, "error": {
            "type": "api", "subtype": "forbidden",
            "message": "comment is solved, cannot reply", "hint": None}},
        "exit": 0,
    }])
    with pytest.raises(LarkApiError) as exc_info:
        reply_comment(DOC, "c_1", "x")
    assert exc_info.value.code == "reply_not_allowed"
