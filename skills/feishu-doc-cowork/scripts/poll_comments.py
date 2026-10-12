"""Poll for owner comments needing processing; exit when found (SPEC §6).

The agent runs this as a long-lived watcher: it sleeps poll_interval ± jitter
between polls and prints a JSON array of candidate comments (then exits 0)
the moment any owner comment is new or was edited since last processed.

CLI:  python poll_comments.py <doc_id> <owner_id> [interval] [jitter]
"""

import json
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cowork_core.tools.comments import list_comments  # noqa: E402
import state  # noqa: E402


def find_candidates(doc_id, owner_id):
    st = state.load(_doc_dir(doc_id))
    out = []
    for c in list_comments(doc_id):
        if c["user_id"] != owner_id:
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
