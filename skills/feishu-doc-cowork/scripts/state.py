"""state.json atomic read/write and crash recovery (SPEC §7.5, D12).

Usage as CLI:  python state.py <doc_dir> <load|upsert|reset-processing> [...]
"""

import json
import os
import sys
import tempfile
import time

STATE_FILE = "state.json"


def _path(doc_dir):
    return os.path.join(doc_dir, STATE_FILE)


def _atomic_write(doc_dir, data):
    fd, tmp = tempfile.mkstemp(dir=doc_dir, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _path(doc_dir))


def load(doc_dir):
    """Load state.json; missing file -> empty structure."""
    try:
        with open(_path(doc_dir), encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"doc_id": None, "comments": {}}


def upsert(doc_dir, comment_id, status, update_time=None, commit_sha=None,
           summary=None, error=None):
    """Insert/update one comment entry and persist atomically."""
    data = load(doc_dir)
    entry = data["comments"].get(comment_id, {})
    entry.update({
        "status": status,
        "update_time": update_time if update_time is not None
                       else entry.get("update_time"),
        "commit_sha": commit_sha if commit_sha is not None
                      else entry.get("commit_sha"),
        "summary": summary if summary is not None else entry.get("summary"),
        "error": error,
        "updated_at": int(time.time()),
    })
    data["comments"][comment_id] = entry
    _atomic_write(doc_dir, data)
    return entry


def reset_processing(doc_dir):
    """Crash recovery: processing -> pending (SPEC §7.5). Returns reset ids."""
    data = load(doc_dir)
    reset = [cid for cid, e in data["comments"].items()
             if e.get("status") == "processing"]
    for cid in reset:
        data["comments"][cid]["status"] = "pending"
    if reset:
        _atomic_write(doc_dir, data)
    return reset


def main(argv):
    doc_dir, cmd = argv[1], argv[2]
    if cmd == "load":
        print(json.dumps(load(doc_dir), ensure_ascii=False, indent=2))
    elif cmd == "upsert":
        upsert(doc_dir, argv[3], argv[4])
    elif cmd == "reset-processing":
        print(json.dumps(reset_processing(doc_dir), ensure_ascii=False))
    else:
        raise SystemExit(f"unknown command: {cmd}")


if __name__ == "__main__":
    main(sys.argv)
