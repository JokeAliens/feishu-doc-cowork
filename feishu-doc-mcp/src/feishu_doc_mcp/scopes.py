"""Minimal scope set — single source of truth (SPEC §4.2, D4).

README's scope table is generated from this list; keep them in sync.
Granularity verified via `lark-cli schema <method>` where the service is
known to schema; docx/board scopes verified via `lark-cli auth check`.
"""

REQUIRED_SCOPES = [
    "docs:document.comment:read",      # schema drive.file.comments.list
    "docs:document.comment:create",    # schema drive.file.comment.replys.create
    "drive:drive.metadata:readonly",   # schema drive.metas.batch_query
    "docx:document:readonly",          # docx blocks read (not in schema; auth check)
    "docx:document",                   # docx blocks write (not in schema; auth check)
    "board:whiteboard:node:read",      # whiteboard read (not in schema; auth check)
    "board:whiteboard:node:create",    # whiteboard node create
    "board:whiteboard:node:update",    # whiteboard node update
    "board:whiteboard:node:delete",    # whiteboard node delete
]
