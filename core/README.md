# cowork core（`cowork` CLI）

lark-cli 的薄封装逻辑层 + CLI（原 MCP 层，v0.2 去除协议壳）。无状态、无缓存、无意图判断。

## 契约

- 每个内部 lark-cli 调用带 `--json`；成功 = envelope `ok == true` + exit 0（exit≠0 但 stdout 为合法 envelope 时按 envelope 处理，如 +update degrade）。
- 写操作先 `--dry-run` 再真实执行。
- **每个子命令 stdout 输出一个 JSON 对象**：成功为结果本身（exit 0）；失败为 `{"error": {"code", "message", "lark_code", "hint"}}`（exit 1，`hint` 透传 lark-cli，供 agent 自修复）。
- 环境变量：`LARK_CLI_BIN`（默认 `lark-cli`）、`LARK_CLI_BIN_ARGS`（测试注入用）。

## 子命令（恰 8 个，之外一概不提供）

### `cowork check-environment`

`auth status` + 全量 scope `auth check`。
出参：`{logged_in: bool, missing_scopes: [str], suggested_login_command: str}`（只含缺失 scope）。

### `cowork get-doc-info <doc_url>`

支持 `https://xxx.feishu.cn/docx/{token}`、裸 token、wiki URL（自动解包）；旧版 `/doc/` 报错提示迁移。
出参：`{doc_id, doc_type: "docx", title, owner_id}`。

### `cowork read-document <doc_id>`

`docs +fetch --doc-format xml --detail with-ids`（with-ids 对 markdown 无效，2026-10-12 实测），DocxXML 解析为 markdown + 块映射。
出参：`{markdown, block_map: [{line, block_id, block_type, parent_id, child_index, row_index?, col_index?, whiteboard_token?}], revision_id}`。
block_map 行号指向生成的 markdown（1 基），可逆寻址；表格单元格带 row_index/col_index（child_index 为全表扁平序）；列表项带 parent_id。非空内容解析不出任何带 id 块时报 `block_map_unresolved`（拒绝盲改）。

### `cowork list-comments <doc_id> [--solved]`

`drive +list-comments`，`--page-token` 自动翻页。出参按 create_time 升序：
`[{comment_id, user_id, create_time, update_time, content, quote, reply_count, replier_ids, is_solved, is_whole}]`。
评论正文取自 `reply_list.replies` 中 create_time 最早的一条（真实 API 形状，2026-10-12 校准）。`replier_ids` 为线程全部参与者的 user_id 列表，供调用方判断「owner 回复背书」（replier_ids 含 owner_id → 等同 owner 评论）。

### `cowork get-comment-thread <doc_id> <comment_id>`

出参：`{comment: {...同上}, replies: [{reply_id, user_id, create_time, update_time, content}]}`。

### `cowork apply-ops <doc_id> --ops <json|@file|-> --expected-revision N`

执行前比对最新 revision，不一致返回 `CONFLICT` 错误且不产生任何写请求。批内每个写请求携带 `--revision-id=N`（粘连形式），并链式更新为上一个写响应返回的新 revision（响应无 revision 时传 -1=latest）。批内中途失败报 `PartialApplyError`（message 含「已应用前 N 项」列表）——调用方必须在失败回复中如实列出。出参：`{results: [{op, status, ...}], revision_id}`。

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

### `cowork reply <doc_id> <comment_id> <content>`

`drive +add-reply`，content 自动包装为 `[{"type":"text","text":...}]`。solved/whole 评论的回复失败映射为 `reply_not_allowed`。

### `cowork resolve <doc_id> <comment_id>`

`drive +resolve-comment`，将评论标记解决并隐藏；solved 评论不再进入默认轮询，处理闭环。

## 开发

```bash
uv sync && uv run pytest tests/    # stub lark-cli，无需真实授权
```
