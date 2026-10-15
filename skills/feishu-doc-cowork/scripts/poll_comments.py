"""Poll for owner comments needing processing; exit when found (SPEC §6).

The agent runs this as a long-lived watcher: it sleeps poll_interval ± jitter
between polls and prints a JSON array of candidate comments (then exits 0)
the moment any owner comment is new or was edited since last processed.

Environment contract (v1.0.2): the skill may be installed standalone via
`npx skills add`, so the only guarantee is the `cowork` executable on PATH
(README install path). All Feishu access goes through it via subprocess —
no cowork_core imports (COWORK_BIN env var overrides the binary for tests).

CLI:  python poll_comments.py <doc_id> <owner_id> [interval] [jitter]
"""

import json
import os
import random
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import state  # noqa: E402  (same-directory skill script)


def _list_comments(doc_id):
    """`cowork list-comments <doc_id>` via subprocess; returns the parsed array."""
    binary = os.environ.get("COWORK_BIN", "cowork")
    proc = subprocess.run([binary, "list-comments", doc_id],
                          capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise RuntimeError(f"cowork list-comments failed: {proc.stdout.strip()[:300]}")
    return json.loads(proc.stdout)


def find_candidates(doc_id, owner_id):
    st = state.load(_doc_dir(doc_id))
    out = []
    for c in _list_comments(doc_id):
        # owner 本人的评论，或 owner 回复过（背书）的他人评论
        if c["user_id"] != owner_id and owner_id not in c.get("replier_ids", []):
            continue
        entry = st["comments"].get(c["comment_id"])
        if entry is None or entry.get("update_time", 0) < c["update_time"]:
            if entry is None or entry.get("status") != "processing":
                out.append(c)
    return out


def _doc_dir(doc_id):
    return os.path.expanduser(f"~/.cache/feishu-doc-cowork/{doc_id}")


def main(argv):
    doc_id, owner_id = argv[1], argv[2]
    interval = float(argv[3]) if len(argv) > 3 else 10.0
    jitter = float(argv[4]) if len(argv) > 4 else 0.2
    while True:
        candidates = find_candidates(doc_id, owner_id)
        if candidates:
            print(json.dumps(candidates, ensure_ascii=False))
            return 0
        time.sleep(interval * (1 + random.uniform(-jitter, jitter)))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
