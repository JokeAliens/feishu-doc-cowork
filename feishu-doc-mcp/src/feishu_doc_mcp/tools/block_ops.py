"""apply_block_operations tool (SPEC §5.6, §8; red lines D7/D16).

Every write goes through lark-cli with --dry-run preview first. No code path
may issue a full-document overwrite/append; validate_operations enforces it.
"""

import json
import logging
import os
import tempfile

from ..cli_runner import run_lark_cli, unwrap
from ..errors import LarkApiError

log = logging.getLogger(__name__)

_DOC_UPDATE_CMDS = {"str_replace", "block_replace", "block_insert_after",
                    "block_delete", "block_move_after"}

_ALLOWED_OPS = {
    "update_text", "replace_block", "insert_blocks", "delete_blocks",
    "move_blocks", "update_table_cells", "table_insert_rows",
    "table_insert_columns", "table_delete_rows", "table_delete_columns",
    "update_board",
}
_FORBIDDEN_TOKENS = ("overwrite", "append")

_REVISION_KEYS = ("revision_id", "revision")


class ConflictError(LarkApiError):
    """Document revision changed between planning and execution (SPEC §8)."""

    def __init__(self, expected, actual):
        super().__init__(
            code="CONFLICT",
            message=f"文档 revision 已变化：expected={expected}, actual={actual}",
        )
        self.expected = expected
        self.actual = actual


def _current_revision(doc_id):
    data = unwrap(run_lark_cli([
        "docs", "+fetch", "--doc", doc_id,
        "--doc-format", "markdown", "--detail", "simple",
        "--scope", "outline", "--max-depth", "1",
    ]))
    for key in _REVISION_KEYS:
        if isinstance(data, dict) and data.get(key) is not None:
            return data[key]
    raise LarkApiError(code="revision_unavailable",
                       message="无法从 +fetch 响应获取 revision_id")


def validate_operations(operations):
    """Reject unknown ops and any full-overwrite semantics before any I/O."""
    for op in operations:
        op_type = op.get("type", "")
        if op_type not in _ALLOWED_OPS:
            raise ValueError(f"unsupported or forbidden op type: {op_type!r}")
        for token in _FORBIDDEN_TOKENS:
            if token in op_type:
                raise ValueError(f"full-overwrite op forbidden: {op_type!r}")


def _expand(operations):
    """Expand ops into atomic write units; each unit issues exactly one write.

    update_table_cells expands to one unit per cell, so the invariant
    'writes == len(units)' holds per SPEC §5.6 (writes <= ops + 1 counts
    expanded units as ops).
    """
    units = []
    for op in operations:
        if op["type"] == "update_table_cells":
            for cell in op["cells"]:
                units.append(("update_text_cell", {
                    "block_id": cell["block_id"],
                    "content_xml": cell["content_xml"],
                }))
        else:
            units.append((op["type"], op))
    return units


def _update_argv(doc_id, command, op, revision_id):
    argv = ["docs", "+update", "--doc", doc_id, "--command", command]
    if op.get("block_id"):
        argv += ["--block-id", op["block_id"]]
    else:
        argv += ["--start-block-id", op["start_block_id"],
                 "--end-block-id", op["end_block_id"]]
    return argv


def _unit_argv(doc_id, unit, revision_id, tmp_dir):
    """Translate one write unit to a lark-cli argv."""
    kind, op = unit
    if kind == "update_text":
        argv = _update_argv(doc_id, "str_replace", op, revision_id)
        return argv + ["--pattern", op["old_text"], "--content", op["new_text"],
                       "--revision-id", str(revision_id)]
    if kind == "replace_block":
        argv = _update_argv(doc_id, "block_replace", op, revision_id)
        return argv + ["--content", op["content_xml"], "--doc-format", "xml"]
    if kind == "insert_blocks":
        return ["docs", "+update", "--doc", doc_id, "--command", "block_insert_after",
                "--block-id", op["after_block_id"],
                "--content", op["content_xml"], "--doc-format", "xml"]
    if kind == "delete_blocks":
        return _update_argv(doc_id, "block_delete", op, revision_id)
    if kind == "move_blocks":
        return ["docs", "+update", "--doc", doc_id, "--command", "block_move_after",
                "--block-id", op["block_id"],
                "--src-block-ids", ",".join(op["src_block_ids"])]
    if kind == "update_text_cell":
        return ["docs", "+update", "--doc", doc_id, "--command", "block_replace",
                "--block-id", op["block_id"],
                "--content", op["content_xml"], "--doc-format", "xml"]
    if kind in ("table_insert_rows", "table_insert_columns",
                "table_delete_rows", "table_delete_columns"):
        field, body = _table_patch_body(kind, op)
        return ["api", "PATCH",
                f"/open-apis/docx/v1/documents/{doc_id}/blocks/{op['table_block_id']}",
                "--data", json.dumps({field: body}, ensure_ascii=False)]
    if kind == "update_board":
        fd, path = tempfile.mkstemp(suffix=".dsl", dir=tmp_dir)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(op["dsl"])
        return ["whiteboard", "+update", "--whiteboard-token", op["whiteboard_token"],
                "--source", f"@{path}", "--input_format", "raw"]
    raise ValueError(f"no translation for unit kind: {kind!r}")


def _table_patch_body(kind, op):
    if kind == "table_insert_rows":
        return "insert_table_row", {"row_index": op["row_index"], "count": op.get("count", 1)}
    if kind == "table_insert_columns":
        return "insert_table_column", {"column_index": op["column_index"], "count": op.get("count", 1)}
    if kind == "table_delete_rows":
        return "delete_table_rows", {"row_start_index": op["row_start_index"],
                                     "row_end_index": op["row_end_index"]}
    return "delete_table_columns", {"column_start_index": op["column_start_index"],
                                    "column_end_index": op["column_end_index"]}


def apply_block_operations(doc_id, operations, expected_revision_id):
    """Apply block-level ops serially; conflict-checked, dry-run-previewed.

    Returns {"results": [...], "revision_id": int}.
    """
    validate_operations(operations)
    units = _expand(operations)

    actual = _current_revision(doc_id)
    if actual != expected_revision_id:
        raise ConflictError(expected_revision_id, actual)

    results = []
    write_count = 0
    with tempfile.TemporaryDirectory() as tmp_dir:
        for unit in units:
            kind, op = unit
            argv = _unit_argv(doc_id, unit, expected_revision_id, tmp_dir)
            preview = run_lark_cli(argv, dry_run=True)
            log.debug("dry-run for %s: %s", kind, json.dumps(preview, ensure_ascii=False))
            try:
                unwrap(run_lark_cli(argv))
                write_count += 1
            except LarkApiError as e:
                if kind == "update_board":
                    results.append({"op": kind, "status": "BOARD_UNSUPPORTED",
                                    "message": e.message, "hint": e.hint})
                    continue
                raise
            assert write_count <= len(units), "write request count exceeded plan units"
            results.append({"op": kind, "status": "ok",
                            "block_id": op.get("block_id") or op.get("table_block_id")})
    return {"results": results, "revision_id": _current_revision(doc_id)}
