"""Minimal scope set — single source of truth (SPEC §4.2, D4).

README's scope table is generated from this list; keep them in sync.
Granularity verified via `lark-cli schema <method>` where the service is
known to schema; docx/board scopes verified via `lark-cli auth check`.
"""

REQUIRED_SCOPES = [
    "docs:document.comment:read",      # schema drive.file.comments.list
    "docs:document.comment:create",    # schema drive.file.comment.replys.create
    "docs:document.comment:update",    # resolve 评论（schema drive file.comments patch 最细项）
    "drive:drive.metadata:readonly",   # schema drive.metas.batch_query
    "docx:document:readonly",          # docx blocks read (not in schema; auth check)
    "docx:document",                   # docx blocks write (not in schema; auth check)
    "board:whiteboard:node:read",      # whiteboard read (not in schema; auth check)
    "board:whiteboard:node:create",    # whiteboard node create
    "board:whiteboard:node:delete",    # whiteboard node delete
    # NOTE: no board:whiteboard:node:update exists for this app (auth scopes
    #实测 2026-10-12); +update works via node create/delete.
]
