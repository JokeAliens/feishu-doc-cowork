"""Git version management for the cowork loop (SPEC §7, D9/D10/D15).

One comment = exactly one commit. Commit messages follow §7.3 verbatim so
`git log --oneline` alone audits every change.

CLI:  python git_ops.py <doc_dir> <ensure-repo|has-doc-diff> [...]
"""

import os
import subprocess
import sys

GIT_ENV = ["-c", "user.name=feishu-doc-cowork",
           "-c", "user.email=feishu-doc-cowork@local"]

GITIGNORE = "*.tmp\n__pycache__/\n"


def _git(doc_dir, *args, check=True):
    proc = subprocess.run(["git", *GIT_ENV, "-C", doc_dir, *args],
                          capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc


def ensure_repo(doc_dir):
    """Create doc_dir with a git repo and .gitignore (idempotent, SPEC D9)."""
    os.makedirs(doc_dir, exist_ok=True)
    gitignore = os.path.join(doc_dir, ".gitignore")
    if not os.path.exists(gitignore):
        with open(gitignore, "w", encoding="utf-8") as f:
            f.write(GITIGNORE)
    if not os.path.isdir(os.path.join(doc_dir, ".git")):
        _git(doc_dir, "init")


def has_doc_diff(doc_dir):
    """True if document.md differs from HEAD (empty-change guard, SPEC §7.2)."""
    proc = _git(doc_dir, "status", "--porcelain", "--", "document.md")
    return bool(proc.stdout.strip())


def _truncate(text, limit):
    return text if len(text) <= limit else text[:limit]


def commit_comment(doc_dir, comment_id, comment_text, summary, block_ids,
                   model_name, agent_name, status="done"):
    """Commit all current changes with the §7.3 message; returns the sha."""
    first_line = _truncate(comment_text.splitlines()[0] if comment_text.strip()
                           else "(空评论)", 50)
    message = (
        f"[comment:{comment_id}] {first_line}\n"
        f"\n"
        f"评论全文:\n{comment_text}\n"
        f"\n"
        f"处理摘要:\n{summary}\n"
        f"\n"
        f"修改块: {', '.join(block_ids)}\n"
        f"AI模型: {model_name} / Agent: {agent_name}\n"
        f"状态: {status}\n"
    )
    _git(doc_dir, "add", "-A")
    _git(doc_dir, "commit", "-m", message)
    return _git(doc_dir, "rev-parse", "HEAD").stdout.strip()


def main(argv):
    doc_dir, cmd = argv[1], argv[2]
    if cmd == "ensure-repo":
        ensure_repo(doc_dir)
    elif cmd == "has-doc-diff":
        print("true" if has_doc_diff(doc_dir) else "false")
    else:
        raise SystemExit(f"unknown command: {cmd}")


if __name__ == "__main__":
    main(sys.argv)
