"""Tests for the skill helper scripts (state machine, git rules, local backup)."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parents[2] / "skills" / "feishu-doc-cowork" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import backup  # noqa: E402
import git_ops  # noqa: E402
import poll_comments  # noqa: E402
import state  # noqa: E402


# ---------- poll_comments.py (v1.0.2: must work with only `cowork` on PATH) ----------

@pytest.fixture()
def fake_cowork(tmp_path, monkeypatch):
    """Fake `cowork` executable emitting canned list-comments JSON."""
    log = tmp_path / "cowork_calls.jsonl"
    canned = tmp_path / "comments.json"
    bin_path = tmp_path / "cowork"
    bin_path.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        f"open({str(log)!r}, 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n"
        f"print(open({str(canned)!r}).read())\n",
        encoding="utf-8")
    bin_path.chmod(0o755)
    monkeypatch.setenv("COWORK_BIN", str(bin_path))

    def set_comments(comments):
        canned.write_text(json.dumps(comments, ensure_ascii=False), encoding="utf-8")

    return set_comments


def _c(cid, user, utime):
    return {"comment_id": cid, "user_id": user, "create_time": utime,
            "update_time": utime, "content": "x", "quote": "",
            "reply_count": 0, "is_solved": False, "is_whole": False}


def test_poll_owner_reply_endorses_others_comment(tmp_path, fake_cowork, monkeypatch):
    """v1.0.4 特性 2：他人评论若 owner 在回复中出现 → 视为 owner 评论进入候选。"""
    monkeypatch.setattr(poll_comments, "_doc_dir", lambda d: str(tmp_path / d))
    (tmp_path / "doc1").mkdir()
    endorsed = _c("c_endorsed", "ou_someone", 300)
    endorsed["replier_ids"] = ["ou_someone", "ou_owner"]     # owner 回复过
    plain_other = _c("c_plain", "ou_someone2", 400)
    plain_other["replier_ids"] = ["ou_someone2"]             # owner 未回复
    fake_cowork([endorsed, plain_other])
    out = poll_comments.find_candidates("doc1", "ou_owner")
    assert [c["comment_id"] for c in out] == ["c_endorsed"]


def test_poll_filters_owner_and_update_time(tmp_path, fake_cowork, monkeypatch):
    """owner 过滤 + state update_time 判重，经 subprocess cowork 取数。"""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr(poll_comments, "_doc_dir", lambda d: str(tmp_path / d))
    (tmp_path / "doc1").mkdir()
    state.upsert(str(tmp_path / "doc1"), "c_done", "done", update_time=100)

    fake_cowork([
        _c("c_done", "ou_owner", 100),      # 已处理且未变 → 跳过
        _c("c_edited", "ou_owner", 200),    # 不在 state → 候选
        _c("c_other", "ou_someone", 300),   # 非 owner → 跳过
    ])
    out = poll_comments.find_candidates("doc1", "ou_owner")
    assert [c["comment_id"] for c in out] == ["c_edited"]


def test_poll_edited_comment_reprocesses(tmp_path, fake_cowork, monkeypatch):
    monkeypatch.setattr(poll_comments, "_doc_dir", lambda d: str(tmp_path / d))
    (tmp_path / "doc1").mkdir()
    state.upsert(str(tmp_path / "doc1"), "c_done", "done", update_time=100)
    fake_cowork([_c("c_done", "ou_owner", 150)])  # update_time 变新 → 重新处理
    out = poll_comments.find_candidates("doc1", "ou_owner")
    assert [c["comment_id"] for c in out] == ["c_done"]


# ---------- state.py ----------

def test_state_identity_roundtrip(tmp_path):
    """v1.0.3: identity 由 agent 在 watcher 启动时自问自报并落盘。"""
    state.set_identity(str(tmp_path), model_name="zai/glm-5.3-flash:high",
                       agent_name="OMP")
    data = state.load(str(tmp_path))
    assert data["identity"]["model_name"] == "zai/glm-5.3-flash:high"
    assert data["identity"]["agent_name"] == "OMP"
    assert data["identity"]["captured_at"] > 0
    # 重新判断（换模型）会覆盖
    state.set_identity(str(tmp_path), model_name="deepseek-v4", agent_name="OMP")
    assert state.load(str(tmp_path))["identity"]["model_name"] == "deepseek-v4"


def test_state_identity_absent_by_default(tmp_path):
    assert state.load(str(tmp_path)).get("identity") is None


def test_state_upsert_load_roundtrip(tmp_path):
    state.upsert(str(tmp_path), "c_1", "done", update_time=100,
                 commit_sha="a1b2c3d", summary="改标题", error=None)
    data = state.load(str(tmp_path))
    entry = data["comments"]["c_1"]
    assert entry["status"] == "done"
    assert entry["update_time"] == 100
    assert entry["commit_sha"] == "a1b2c3d"
    assert entry["summary"] == "改标题"
    assert entry["error"] is None
    assert entry["updated_at"] > 0


def test_state_load_missing_returns_empty(tmp_path):
    data = state.load(str(tmp_path))
    assert data["comments"] == {}


def test_state_reset_processing(tmp_path):
    state.upsert(str(tmp_path), "c_1", "processing")
    state.upsert(str(tmp_path), "c_2", "done")
    state.upsert(str(tmp_path), "c_3", "processing")
    reset = state.reset_processing(str(tmp_path))
    assert sorted(reset) == ["c_1", "c_3"]
    data = state.load(str(tmp_path))
    assert data["comments"]["c_1"]["status"] == "pending"
    assert data["comments"]["c_3"]["status"] == "pending"
    assert data["comments"]["c_2"]["status"] == "done"


# ---------- git_ops.py ----------

def _git(doc_dir, *args):
    return subprocess.run(["git", "-C", str(doc_dir), *args],
                          capture_output=True, text=True, check=True).stdout


def test_ensure_repo(tmp_path):
    doc_dir = tmp_path / "doc1"
    git_ops.ensure_repo(str(doc_dir))
    assert (doc_dir / ".git").is_dir()
    gitignore = (doc_dir / ".gitignore").read_text()
    assert "*.tmp" in gitignore and "__pycache__/" in gitignore
    # idempotent
    git_ops.ensure_repo(str(doc_dir))


def test_commit_comment_message_format(tmp_path):
    doc_dir = tmp_path / "doc1"
    git_ops.ensure_repo(str(doc_dir))
    (doc_dir / "document.md").write_text("内容v1\n", encoding="utf-8")
    sha = git_ops.commit_comment(
        str(doc_dir), comment_id="c_1",
        comment_text="把第三章标题改成「部署方案」",
        summary="将第三章标题更新为部署方案",
        block_ids=["blk004", "blk005"],
        model_name="GLM5.3", agent_name="OMP", status="done",
    )
    assert sha
    msg = _git(doc_dir, "log", "-1", "--format=%B")
    assert msg.startswith("[comment:c_1] 把第三章标题改成「部署方案」")
    assert "评论全文:\n把第三章标题改成「部署方案」" in msg
    assert "处理摘要:\n将第三章标题更新为部署方案" in msg
    assert "修改块: blk004, blk005" in msg
    assert "AI模型: GLM5.3 / Agent: OMP" in msg
    assert "状态: done" in msg


def test_commit_comment_truncates_first_line_at_50(tmp_path):
    doc_dir = tmp_path / "doc1"
    git_ops.ensure_repo(str(doc_dir))
    (doc_dir / "document.md").write_text("x\n", encoding="utf-8")
    long_comment = "把" + "很" * 80 + "长的评论"
    git_ops.commit_comment(
        str(doc_dir), comment_id="c_2", comment_text=long_comment,
        summary="s", block_ids=[], model_name="M", agent_name="A", status="done",
    )
    first_line = _git(doc_dir, "log", "-1", "--format=%s").strip()
    # "[comment:c_2] " is 14 chars; comment part truncated to 50
    assert len(first_line) == len("[comment:c_2] ") + 50


def test_two_comments_two_commits(tmp_path):
    doc_dir = tmp_path / "doc1"
    git_ops.ensure_repo(str(doc_dir))
    for i, cid in enumerate(("c_1", "c_2")):
        (doc_dir / "document.md").write_text(f"内容v{i}\n", encoding="utf-8")
        git_ops.commit_comment(str(doc_dir), comment_id=cid,
                               comment_text=f"评论{cid}", summary="s",
                               block_ids=["b"], model_name="M",
                               agent_name="A", status="done")
    log = _git(doc_dir, "log", "--format=%s").strip().splitlines()
    assert len(log) == 2
    assert "[comment:c_2]" in log[0] and "[comment:c_1]" in log[1]


def test_has_doc_diff(tmp_path):
    doc_dir = tmp_path / "doc1"
    git_ops.ensure_repo(str(doc_dir))
    (doc_dir / "document.md").write_text("v1\n", encoding="utf-8")
    assert git_ops.has_doc_diff(str(doc_dir)) is True
    git_ops.commit_comment(str(doc_dir), comment_id="c_1", comment_text="t",
                           summary="s", block_ids=[], model_name="M",
                           agent_name="A", status="done")
    assert git_ops.has_doc_diff(str(doc_dir)) is False
    (doc_dir / "document.md").write_text("v1\n", encoding="utf-8")
    assert git_ops.has_doc_diff(str(doc_dir)) is False
    (doc_dir / "document.md").write_text("v2\n", encoding="utf-8")
    assert git_ops.has_doc_diff(str(doc_dir)) is True


# ---------- backup.py ----------

def _make_backup(doc_dir, revision):
    return backup.create_backup(
        str(doc_dir), doc_id="docX", title="测试文档", revision_id=revision,
        document_md=f"内容 rev{revision}\n",
        block_map_json=json.dumps([{"line": 1, "block_id": "b1"}]),
    )


def test_backup_writes_snapshot_and_mapping(tmp_path):
    rec = _make_backup(tmp_path, 7)
    path = Path(rec["path"])
    assert path.is_dir()
    assert (path / "document.md").read_text(encoding="utf-8") == "内容 rev7\n"
    assert json.loads((path / "block_map.json").read_text()) == [{"line": 1, "block_id": "b1"}]
    mapping = json.loads((tmp_path / "backups.json").read_text(encoding="utf-8"))
    assert mapping["doc_id"] == "docX"
    assert mapping["backups"][0]["revision_id"] == 7
    assert mapping["backups"][0]["ts"] == rec["ts"]


def test_backup_keeps_only_three(tmp_path):
    recs = [_make_backup(tmp_path, r) for r in (1, 2, 3, 4)]
    dirs = sorted(p.name for p in (tmp_path / "backups").iterdir() if p.is_dir())
    assert len(dirs) == 3
    # oldest (revision 1) pruned from disk and mapping
    assert not Path(recs[0]["path"]).exists()
    mapping = json.loads((tmp_path / "backups.json").read_text(encoding="utf-8"))
    assert len(mapping["backups"]) == 3
    assert [b["revision_id"] for b in mapping["backups"]] == [4, 3, 2]
