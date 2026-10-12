"""Local document backup at skill startup (SPEC D17).

Pure local: timestamped snapshot copies inside the doc's git directory,
mapping recorded in backups.json, committed once by the caller via
git_ops. Only the newest `keep` backups are retained; older ones are
deleted locally. No cloud-drive operation.

CLI:  python backup.py <doc_dir> <doc_id> <title> <revision_id>
      (document.md/block_map.json read from doc_dir)
"""

import json
import os
import shutil
import sys
import time

BACKUPS_DIR = "backups"
BACKUPS_JSON = "backups.json"
DEFAULT_KEEP = 3


def _timestamp():
    return time.strftime("%Y%m%d-%H%M%S")


def _load_mapping(doc_dir, doc_id):
    path = os.path.join(doc_dir, BACKUPS_JSON)
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"doc_id": doc_id, "backups": []}


def _unique_dir(base):
    candidate = base
    n = 1
    while os.path.exists(candidate):
        n += 1
        candidate = f"{base}-{n}"
    return candidate


def create_backup(doc_dir, doc_id, title, revision_id, document_md,
                  block_map_json, keep=DEFAULT_KEEP):
    """Snapshot document.md + block_map.json into backups/{ts}/.

    Updates backups.json (newest first) and prunes to `keep` entries,
    deleting older backup directories. Returns the new record:
    {"ts", "path", "revision_id", "title"}.
    """
    backups_root = os.path.join(doc_dir, BACKUPS_DIR)
    ts = _timestamp()
    dest = _unique_dir(os.path.join(backups_root, ts))
    os.makedirs(dest)
    with open(os.path.join(dest, "document.md"), "w", encoding="utf-8") as f:
        f.write(document_md)
    with open(os.path.join(dest, "block_map.json"), "w", encoding="utf-8") as f:
        f.write(block_map_json)

    mapping = _load_mapping(doc_dir, doc_id)
    record = {"ts": os.path.basename(dest), "path": dest,
              "revision_id": revision_id, "title": title}
    mapping["backups"].insert(0, record)

    while len(mapping["backups"]) > keep:
        old = mapping["backups"].pop()
        shutil.rmtree(old["path"], ignore_errors=True)

    with open(os.path.join(doc_dir, BACKUPS_JSON), "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)
    return record


def main(argv):
    doc_dir, doc_id, title, revision_id = argv[1:5]
    with open(os.path.join(doc_dir, "document.md"), encoding="utf-8") as f:
        document_md = f.read()
    with open(os.path.join(doc_dir, "block_map.json"), encoding="utf-8") as f:
        block_map_json = f.read()
    rec = create_backup(doc_dir, doc_id, title, int(revision_id),
                        document_md, block_map_json)
    print(json.dumps(rec, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv)
