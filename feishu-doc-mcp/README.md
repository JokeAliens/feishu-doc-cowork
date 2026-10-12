# feishu-doc-mcp

FastMCP 薄封装层：把 lark-cli 调用包装成结构化 MCP 工具（SPEC §5）。无状态、无缓存、无意图判断。

## 契约

- 每个内部 lark-cli 调用带 `--format json`；成功 = envelope `ok == true` + exit 0。
- 写操作先 `--dry-run` 再真实执行。
- 错误统一返回 `{"error": {"code", "message", "lark_code", "hint"}}`（`hint` 透传 lark-cli，供 agent 自修复），不向客户端抛栈。
- 环境变量：`LARK_CLI_BIN`（默认 `lark-cli`）、`LARK_CLI_BIN_ARGS`（测试注入用）。

## 工具（恰 7 个，SPEC §5.8 之外一概不提供）

### `check_environment() -> dict`

`auth status` + 全量 scope `auth check`。
出参：`{logged_in: bool, missing_scopes: [str], suggested_login_command: str}`（只含缺失 scope）。

### `get_doc_info(doc_url: str) -> dict`

支持 `https://xxx.feishu.cn/docx/{token}`、裸 token、wiki URL（自动解包）；旧版 `/doc/` 报 `LegacyDocError`。
出参：`{doc_id, doc_type: "docx", title, owner_id}`。

### `read_document(doc_id: str) -> dict`

`docs +fetch --doc-format markdown --detail with-ids`。
出参：`{markdown, block_map: [{line, block_id, block_type, parent_id, child_index}], revision_id}`。
block_map 行号指向**剥离记号后的** markdown（1 基），可逆寻址。

### `list_comments(doc_id: str, is_solved: bool = False) -> list`

`drive +list-comments`，`--page-token` 自动翻页。出参按 create_time 升序：
`[{comment_id, user_id, create_time, update_time, content, quote, reply_count, is_solved, is_whole}]`（时间戳为 int 秒）。

### `get_comment_thread(doc_id: str, comment_id: str) -> dict`

出参：`{comment: {...同上}, replies: [{reply_id, user_id, create_time, update_time, content}]}`。

### `apply_block_operations(doc_id: str, operations: list, expected_revision_id: int) -> dict`

执行前比对最新 revision，不一致返回 `CONFLICT` 错误且不产生任何写请求。批内每个写请求携带 `--revision-id`，并链式更新为上一个写响应返回的新 revision（响应无 revision 时传 `-1`=latest，避免严格 CAS 下批内 stale id 被拒绝）。批内中途失败抛 `PartialApplyError`（error.code 透传原因，`message` 含「已应用前 N 项」列表）——调用方必须在失败回复中如实列出。出参：`{results: [{op, status, ...}], revision_id}`。

| op.type | 必填字段 | 通道 |
| --- | --- | --- |
| `update_text` | `block_id, old_text, new_text` | `docs +update --command str_replace` |
| `replace_block` | `block_id` 或 `start_block_id+end_block_id`，`content_xml` | `block_replace` |
| `insert_blocks` | `after_block_id, content_xml` | `block_insert_after` |
| `delete_blocks` | `block_id` 或 `start+end_block_id` | `block_delete` |
| `move_blocks` | `block_id, src_block_ids[]` | `block_move_after` |
| `update_table_cells` | `cells: [{block_id, content_xml}]` | 逐 cell `block_replace`（每 cell 一个写请求） |
| `table_insert_rows` | `table_block_id, row_index, count?` | Raw API PATCH block（`insert_table_row`） |
| `table_insert_columns` | `table_block_id, column_index, count?` | 同上（`insert_table_column`） |
| `table_delete_rows` / `table_delete_columns` | `table_block_id, *_start_index, *_end_index` | 同上 |
| `update_board` | `whiteboard_token, dsl` | `whiteboard +update`（无 `--overwrite`）；不支持图元 → result 标 `BOARD_UNSUPPORTED` |

红线（代码强制）：op 类型白名单，拒绝任何 overwrite/append 语义；写请求数 == 展开后原子写单元数（无全量重建路径）。

### `reply_comment(doc_id: str, comment_id: str, content: str) -> dict`

`drive +add-reply`，content 自动包装为 `[{"type":"text","text":...}]`。solved/whole 评论的回复失败映射为 `reply_not_allowed`。

## 开发

```bash
uv sync && uv run pytest tests/    # stub lark-cli，无需真实授权
```
