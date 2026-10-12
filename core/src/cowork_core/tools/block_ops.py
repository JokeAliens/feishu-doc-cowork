"""apply_block_operations tool (SPEC §5.6, §8; red lines D7/D16).

Every write goes through lark-cli with --dry-run preview first. No code path
may issue a full-document overwrite/append; validate_operations enforces it.

Revision strategy (final-review ruling): `+update --revision-id` semantics
are unproven (strict CAS vs informational). We therefore (a) check the
latest revision once before the batch (fail fast on CONFLICT), and (b) chain
the revision returned by each write into the next write's --revision-id;
when a write response carries no revision we pass -1 (= latest) so a strict
CAS cannot reject a mid-batch write on a stale id.
"""

import json
import logging
import os
import tempfile

from ..cli_runner import run_lark_cli, unwrap
from ..errors import LarkApiError

log = logging.getLogger(__name__)

_ALLOWED_OPS = {
    "update_text", "replace_block", "insert_blocks", "delete_blocks",
    "move_blocks", "update_table_cells", "table_insert_rows",
    "table_insert_columns", "table_delete_rows", "table_delete_columns",
    "update_board",
}

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


class PartialApplyError(LarkApiError):
    """A write failed mid-batch; earlier ops are already live in the doc."""

    def __init__(self, applied, failed_unit, cause):
        self.applied = list(applied)
        super().__init__(
            code=cause.code,
            message=(f"批内部分失败：已应用 {len(self.applied)} 项"
                     f"（{', '.join(self.applied) or '无'}），"
                     f"失败于 {failed_unit}：{cause.message}"),
            hint=cause.hint, lark_code=cause.lark_code,
        )


def _to_int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_revision(data):
    if isinstance(data, dict):
        if isinstance(data.get("document"), dict):
            data = data["document"]
        for key in _REVISION_KEYS:
            rev = _to_int_or_none(data.get(key))
            if rev is not None:
                return rev
    return None


def _current_revision(doc_id):
    data = unwrap(run_lark_cli([
        "docs", "+fetch", "--doc", doc_id,
        "--doc-format", "markdown", "--detail", "simple",
        "--scope", "outline", "--max-depth", "1",
    ]))
    rev = _extract_revision(data)
    if rev is None:
        raise LarkApiError(code="revision_unavailable",
                           message="无法从 +fetch 响应获取 revision_id")
    return rev


def validate_operations(operations):
    """Reject unknown/forbidden op types before any I/O (red line, SPEC §5.6)."""
    for op in operations:
        op_type = op.get("type", "")
        if op_type not in _ALLOWED_OPS:
            raise ValueError(f"unsupported or forbidden op type: {op_type!r}")


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


def _target_argv(argv, op):
    if op.get("block_id"):
        return argv + ["--block-id", op["block_id"]]
    return argv + ["--start-block-id", op["start_block_id"],
                   "--end-block-id", op["end_block_id"]]


def _update(doc_id, command, revision_id):
    # glued form: a bare "-1" token can be misread as an option by argparse
    # style parsers (delta review); --flag=value is unambiguous.
    return ["docs", "+update", "--doc", doc_id, "--command", command,
            f"--revision-id={revision_id}"]


def _unit_label(unit):
    kind, op = unit
    return op.get("block_id") or op.get("table_block_id") \
        or op.get("whiteboard_token") or kind


def _unit_argv(doc_id, unit, revision_id, tmp_dir):
    """Translate one write unit to a lark-cli argv."""
    kind, op = unit
    if kind == "update_text":
        return _target_argv(_update(doc_id, "str_replace", revision_id), op) + [
            "--pattern", op["old_text"], "--content", op["new_text"]]
    if kind == "replace_block":
        return _target_argv(_update(doc_id, "block_replace", revision_id), op) + [
            "--content", op["content_xml"], "--doc-format", "xml"]
    if kind == "insert_blocks":
        return _update(doc_id, "block_insert_after", revision_id) + [
            "--block-id", op["after_block_id"],
            "--content", op["content_xml"], "--doc-format", "xml"]
    if kind == "delete_blocks":
        return _target_argv(_update(doc_id, "block_delete", revision_id), op)
    if kind == "move_blocks":
        return _update(doc_id, "block_move_after", revision_id) + [
            "--block-id", op["block_id"],
            "--src-block-ids", ",".join(op["src_block_ids"])]
    if kind == "update_text_cell":
        return _update(doc_id, "block_replace", revision_id) + [
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
    Raises ConflictError before any write; PartialApplyError if a write
    fails mid-batch (earlier ops already applied — see .applied).
    """
    validate_operations(operations)
    units = _expand(operations)

    actual = _current_revision(doc_id)
    if actual != _to_int_or_none(expected_revision_id):
        raise ConflictError(expected_revision_id, actual)

    results = []
    applied = []
    cur_rev = actual
    with tempfile.TemporaryDirectory() as tmp_dir:
        for unit in units:
            kind, op = unit
            argv = _unit_argv(doc_id, unit, cur_rev, tmp_dir)
            preview = run_lark_cli(argv, dry_run=True)
            log.debug("dry-run for %s: %s", kind, json.dumps(preview, ensure_ascii=False))
            try:
                data = unwrap(run_lark_cli(argv))
            except LarkApiError as e:
                if kind == "update_board":
                    results.append({"op": kind, "status": "BOARD_UNSUPPORTED",
                                    "message": e.message, "hint": e.hint})
                    continue
                raise PartialApplyError(applied, _unit_label(unit), e) from e
            cur_rev = _extract_revision(data) if _extract_revision(data) is not None else -1
            applied.append(_unit_label(unit))
            results.append({"op": kind, "status": "ok",
                            "block_id": op.get("block_id") or op.get("table_block_id")})
    return {"results": results, "revision_id": _current_revision(doc_id)}
