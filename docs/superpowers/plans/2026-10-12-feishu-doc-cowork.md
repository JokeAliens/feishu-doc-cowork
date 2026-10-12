# 飞书文档 AI 协同编辑 Skill + MCP 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按 SPEC.md v2.0 交付「Skill + feishu-doc-mcp」组合：agent 轮询飞书文档 owner 评论，块级增量修改文档，一评论一 commit，回复固定格式。

**Architecture:** lark-cli 是唯一飞书通道；feishu-doc-mcp（FastMCP）做薄封装（子进程调用 + envelope 解析 + 错误归一化），无状态无业务逻辑；skill 包含主循环/意图判定/git 规范/判定提示词，git 走 shell。测试用 stub lark-cli 假二进制注入罐头 envelope，不依赖真实飞书授权。

**Tech Stack:** Python 3.12（uv 管理，spec 要求 ≥3.11）/ FastMCP / lark-cli 1.0.97（已装）/ git / pytest

**Spec:** [SPEC.md](../../../SPEC.md)

## Global Constraints

- Python ≥ 3.11（用 uv pin 3.12，本机已装 cpython-3.12.13）；uv 已配清华源，可直接装依赖。
- 所有 lark-cli 调用带 `--format json`；判成功看 envelope `ok == true` + exit code，**不是** `code == 0`（实测 envelope 为 `{ok, data|error{type,subtype,message,hint}, identity, dry_run}`）。
- 分页：`--page-all --page-delay 500`；写操作先 `--dry-run`。
- **红线**：任何写路径禁止 `overwrite` / `append` / 全量覆盖命令；`apply_block_operations` 一次调用写请求数 ≤ 操作数 + 1。
- 身份固定 `--as user`；配置/代码中不出现 app_id/app_secret/token。
- 一评论 = 恰好一个 commit；空改动不 commit。
- 回复格式逐字：`修改完成，使用AI模型：{model_name}， Agent：{agent_name}`（注意中文逗号 + ASCII 空格）。

## 实测锁定的 lark-cli 事实（计划论据，执行者勿再猜测）

| 用途 | 命令 | 实测依据 |
| --- | --- | --- |
| 读文档（带块 ID） | `docs +fetch --doc {url} --doc-format markdown --detail with-ids` | +fetch --help：with-ids 含 block ID，可直接用于块编辑 |
| 块级文本/结构写 | `docs +update --command str_replace\|block_replace\|block_delete\|block_insert_after\|block_move_after --block-id/--start-block-id/--end-block-id --content ... --revision-id N` | +update --help；`overwrite`/`append` 属全量，禁用 |
| 表格行列/cell、画板外 Raw 端点 | `lark-cli api PATCH /open-apis/docx/v1/documents/{id}/blocks/{bid} --data '{...}'`（路径必须带 `/open-apis` 前缀） | api --help + dry-run 实测 |
| 评论列表 | `drive +list-comments --url {url} --solved-status false --format json` | +list-comments --help |
| 评论线程 | `drive +list-replies --url {url} --comment-id {id}` | drive --help |
| 回复评论 | `drive +add-reply --url {url} --comment-id {id} --content '[{"type":"text","text":"..."}]'` | +add-reply --help（content 为 reply_elements JSON） |
| URL 解析/owner | `drive +inspect`（类型/标题/canonical token/wiki 解包）+ `drive metas batch_query`（owner_id） | drive --help + schema |
| 画板 | `whiteboard +update --whiteboard-token {t} --source @dsl --input_format raw`（默认增量，无 --overwrite） | whiteboard +update --help |
| scope 复核 | `lark-cli schema <service.resource.method>` → `_meta.scopes` 取最细粒度 | 实测见下表 |
| 权限自检 | `auth status --json`（`identities.user.status`）+ `auth check --scope "..." --json` | auth --help 实测 |

**schema 实测 scope（最终清单候选，写进 README；取每项最细粒度）：**

| 能力 | 最细 scope | 来源 |
| --- | --- | --- |
| 评论读 | `docs:document.comment:read` | schema drive.file.comments.list |
| 评论写（回复） | `docs:document.comment:create` | schema drive.file.comment.replys.create |
| 文件元信息（owner） | `drive:drive.metadata:readonly` | schema drive.metas.batch_query |
| docx 块读 | `docx:document:readonly` | docx 不在 schema 服务列表内，README 标注用 `auth check` 复核 |
| docx 块写 | `docx:document` | 同上 |
| 画板 | `board:whiteboard:node:read` + `board:whiteboard:node:create` + `board:whiteboard:node:update` + `board:whiteboard:node:delete`（schema 无 whiteboard 服务，auth status 实测已见 board:whiteboard:node:* 命名空间；README 标注复核方法，若 +update 实测用不了某个 scope 再缩减） | auth status 实测 |

## Review Focus

1. **with-ids markdown 的真实格式未实测**（user token 过期）：block ID 以何种记号嵌入（注释/前缀/行尾）决定 block_map 解析器写法 → Task 3 测试用 stub 按「行尾 `<!-- block_id: xxx -->` 或同类可解析记号」假设实现，解析器必须做成**可配置正则**；Task 9 联调时以真实输出校准正则。
2. **owner_id 字段名未实测**：metas batch_query 返回的 owner 字段可能是 `owner_id`，需按真实 envelope 取 → Task 2 解析器走「候选键列表」并在联调校准。
3. **+update --revision-id 的冲突语义未实测**：未必是严格 CAS → Task 4 必须同时实现 MCP 侧「执行前重拉 revision 比对」，不能只依赖 CLI 参数。
4. **solved/whole 评论不能回复**（+add-reply --help 明示）：reply_comment 遇到此类错误要映射成可识别错误码，skill 侧按 failed 处理而非崩溃 → Task 5 测试覆盖。
5. **分页边界**：+list-comments 用 `--page-token` 而非 `--page-all`（shortcut 无 --page-all 标志），stub 测试要含多页 → Task 5。

---

### Task 1: feishu-doc-mcp 骨架 + cli_runner（envelope 解析与错误映射）

**Files:**
- Create: `feishu-doc-mcp/pyproject.toml`（uv；requires-python `>=3.11`；deps: `fastmcp`；dev-deps: `pytest`）
- Create: `feishu-doc-mcp/src/feishu_doc_mcp/__init__.py`
- Create: `feishu-doc-mcp/src/feishu_doc_mcp/errors.py`
- Create: `feishu-doc-mcp/src/feishu_doc_mcp/cli_runner.py`
- Create: `feishu-doc-mcp/tests/fake_lark_cli.py`（stub：按 argv 匹配 canned 响应文件，输出 envelope JSON 到 stdout、exit code 可控）
- Test: `feishu-doc-mcp/tests/test_cli_runner.py`

**Interfaces:**
- Produces（后续所有 task 依赖）:
  - `run_lark_cli(args: list[str], *, dry_run: bool = False, timeout: float = 60.0) -> dict` — 追加 `--format json`，执行 `lark-cli`，返回 envelope dict；exit≠0 或 JSON 解析失败抛 `CliExecError`。
  - `unwrap(envelope: dict) -> Any` — `ok==true` 返回 `envelope["data"]`；否则抛 `LarkApiError`。
  - `class LarkApiError(Exception)`：属性 `code`（= error.subtype 或 error.type）、`message`、`hint`（透传 error.hint，可为 None）、`lark_code`（envelope error 里的 API 错误码，可 None）。
  - `class CliExecError(Exception)`：二进制缺失/超时/非 JSON 输出。
- Consumes: 无。

- [ ] **Step 1: 写失败测试** — `test_cli_runner.py`：
  - `test_unwrap_ok_returns_data`：`{"ok":true,"data":{"a":1}}` → `{"a":1}`。
  - `test_unwrap_error_raises_with_hint`：`{"ok":false,"error":{"type":"api","subtype":"permission_denied","message":"no scope","hint":"run: lark-cli auth login --scope docs:document.comment:read"}}` → `LarkApiError.code=="permission_denied"`、`hint` 原样透传。
  - `test_run_appends_format_json`：stub 记录 argv，断言含 `--format json`。
  - `test_run_nonzero_exit_raises_cli_exec`。
  - `test_run_invalid_json_raises_cli_exec`。
- [ ] **Step 2: 跑测试确认失败** — `cd feishu-doc-mcp && uv run pytest tests/test_cli_runner.py -v`；预期：ModuleNotFoundError。
- [ ] **Step 3: 实现** — `errors.py` 两个异常类；`cli_runner.py` 用 `subprocess.run(capture_output=True, text=True)`，lark-cli 路径从 `LARK_CLI_BIN` 环境变量读（默认 `lark-cli`，测试注入 stub 路径）；`fake_lark_cli.py` 为可执行 Python 脚本：`FAKE_LARK_DIR` 环境变量指向用例目录，按 `argv 归一化 join` 匹配 `{case}.json`（含 `stdout`、`exit` 字段）输出。
- [ ] **Step 4: 跑测试确认通过**。
- [ ] **Step 5: Commit** — `feat(mcp): cli runner with envelope parsing and error mapping`。

### Task 2: check_environment + get_doc_info（U1）

**Files:**
- Create: `feishu-doc-mcp/src/feishu_doc_mcp/tools/__init__.py`
- Create: `feishu-doc-mcp/src/feishu_doc_mcp/tools/environment.py`
- Create: `feishu-doc-mcp/src/feishu_doc_mcp/tools/doc_info.py`
- Create: `feishu-doc-mcp/src/feishu_doc_mcp/url_parse.py`
- Create: `feishu-doc-mcp/src/feishu_doc_mcp/scopes.py`（最终 scope 清单常量，单一事实源，README 从这里生成表格）
- Test: `feishu-doc-mcp/tests/test_environment.py`、`tests/test_url_parse.py`、`tests/test_doc_info.py`

**Interfaces:**
- Consumes: Task 1 的 `run_lark_cli`/`unwrap`/`LarkApiError`。
- Produces:
  - `REQUIRED_SCOPES: list[str]`（scopes.py，6 项，见实测表）。
  - `check_environment() -> {"logged_in": bool, "missing_scopes": list[str], "suggested_login_command": str}`：`auth status --json` 看 `identities.user.status=="ready"`；逐个 `auth check --scope <s> --json`；missing 非空时拼 `lark-cli auth login --scope "a" --scope "b"`。
  - `parse_doc_url(url_or_token: str) -> {"doc_token": str, "doc_type": "docx"|"wiki"|"doc", "url": str}`：裸 token（无斜杠）默认 docx；`/docx/{token}` 提取；`/wiki/{token}` 标 wiki；`/doc/`（旧版）抛 `LegacyDocError`（明确报错提示迁移）。
  - `get_doc_info(doc_url: str) -> {"doc_id": str, "doc_type": "docx", "title": str, "owner_id": str}`：wiki 先经 `drive +inspect` 解包取 obj_token；owner 经 `drive metas batch_query`（`api POST /open-apis/drive/v1/metas/batch_query`，data `{"request_docs":[{"doc_token":t,"doc_type":"docx"}],"with_url":false}`），owner 字段按候选键 `owner_id`/`owner_open_id` 取，取不到抛带原始响应的错。
  - `class LegacyDocError(Exception)`。
- [ ] **Step 1: 写失败测试** — url_parse 覆盖：完整 docx URL 带 query、裸 token、wiki URL、旧 `/doc/` URL 报 LegacyDocError、垃圾输入报错；environment：stub 给出 user ready + 部分 scope 缺失 → `missing_scopes` 正确、`suggested_login_command` 含且仅含缺失项；doc_info：stub metas 响应 → owner_id 提取。
- [ ] **Step 2–5:** 失败 → 实现 → 通过 → commit `feat(mcp): environment check and doc info`。（每 task 同此节奏，下同）

### Task 3: read_document（U2 可逆寻址）

**Files:**
- Create: `feishu-doc-mcp/src/feishu_doc_mcp/block_map.py`
- Create: `feishu-doc-mcp/src/feishu_doc_mcp/tools/read_doc.py`
- Test: `feishu-doc-mcp/tests/test_read_doc.py`

**Interfaces:**
- Consumes: Task 1、Task 2 `parse_doc_url`。
- Produces:
  - `BLOCK_ID_PATTERN: re.Pattern`（block_map.py 顶部常量，**唯一**解析点，联调时只改这里；默认匹配行尾 `<!-- block_id: {id} -->` 及 `^{id} ` 前缀两类记号）。
  - `parse_fetch_output(data: dict) -> {"markdown": str, "block_map": list[BlockEntry], "revision_id": int}`；`BlockEntry = {"line": int, "block_id": str, "block_type": str|None, "parent_id": str|None, "child_index": int|None}`。
  - `read_document(doc_id: str) -> {"markdown", "block_map", "revision_id"}`：`docs +fetch --doc {id} --doc-format markdown --detail with-ids --scope full --format json`。
- [ ] **Step 1: 写失败测试** — 构造含 10 个块记号的罐头 fetch 输出：断言 block_map 长度、每条的 line↔block_id 与 markdown 行一致；随机抽 3 行反查 block_id 正确；无记号行（空行/分隔）不产生 entry；revision_id 从 envelope data 提取。
- [ ] **Step 2–5:** 标准节奏 → commit `feat(mcp): read_document with reversible block map`。

### Task 4: apply_block_operations（U3 + 红线）

**Files:**
- Create: `feishu-doc-mcp/src/feishu_doc_mcp/tools/block_ops.py`
- Test: `feishu-doc-mcp/tests/test_block_ops.py`

**Interfaces:**
- Consumes: Task 1–3。
- Produces:
  - `apply_block_operations(doc_id: str, operations: list[dict], expected_revision_id: int) -> {"results": list[dict], "revision_id": int}`。
  - op 翻译表（op → lark-cli 调用）：
    - `update_text{block_id, old_text, new_text}` → `docs +update --command str_replace --block-id {bid} --pattern {old} --content {new} --revision-id {rev}`
    - `replace_block{block_id|start_block_id+end_block_id, content_xml}` → `docs +update --command block_replace ...`（content 默认 DocxXML，`--doc-format xml`）
    - `insert_blocks{after_block_id, content_xml}` → `block_insert_after`
    - `delete_blocks{block_id|start+end}` → `block_delete`
    - `move_blocks{block_id, src_block_ids}` → `block_move_after`
    - `update_table_cells{cells:[{block_id, content_xml}]}` → 逐 cell `docs +update --command block_replace --block-id {cell_bid}`（每 cell 一个请求）
    - `table_insert_rows{table_block_id, row_index, count}` / `table_insert_columns{...}` / `table_delete_rows` / `table_delete_columns` → Raw API `PATCH /open-apis/docx/v1/documents/{id}/blocks/{table_bid}` data `{"insert_table_row":{"row_index":n,...}}` 等（联调校准字段名）
    - `update_board{whiteboard_token, dsl}` → `whiteboard +update --whiteboard-token {t} --source @tmp --input_format raw`（**禁止** `--overwrite`）；不支持图元 → 结果标 `BOARD_UNSUPPORTED`
  - 冲突：执行前 `docs +fetch --revision-id -1` 取最新 revision 与 expected 比对，不一致抛 `ConflictError`（`code=="CONFLICT"`）。
  - 护栏（红线机械化）：`validate_operations()` 拒绝任何含 `overwrite`/`append` 语义的 op 或字段；统计实际写请求数 > len(ops)+1 时抛内部错误（防回归）。
  - 每个写调用先 dry_run=True 再真实执行，dry-run 输出进 `logging.debug`。
  - `class ConflictError(LarkApiError)`。
- [ ] **Step 1: 写失败测试** — stub 记录全部 argv：单句 update_text 只产生 1 个写调用且 argv 含 `str_replace` 不含 `overwrite`（U3）；revision 不匹配抛 ConflictError 且零写请求；含 `overwrite` op 被 validate 拒绝；replace_block 组合产生恰好 1 个写调用（block_replace 单命令，验证 ≤ ops+1）；board op 调 whiteboard +update 且无 --overwrite。
- [ ] **Step 2–5:** 标准节奏 → commit `feat(mcp): block operations with conflict detection and overwrite guard`。

### Task 5: 评论三工具（U4 数据面）

**Files:**
- Create: `feishu-doc-mcp/src/feishu_doc_mcp/tools/comments.py`
- Test: `feishu-doc-mcp/tests/test_comments.py`

**Interfaces:**
- Produces:
  - `list_comments(doc_id: str, is_solved: bool = False) -> list[dict]`：`drive +list-comments --url {doc_id} --solved-status {false|all} --format json`，循环 `--page-token` 至无下一页（Review Focus #5）；归一化出参 `{comment_id, user_id, create_time, update_time, content, quote, reply_count, is_solved, is_whole}`，按 create_time 升序。
  - `get_comment_thread(doc_id: str, comment_id: str) -> {"comment": dict, "replies": list[dict]}`：batch_query 主评论 + `+list-replies`。
  - `reply_comment(doc_id: str, comment_id: str, content: str) -> dict`：`+add-reply --content '[{"type":"text","text":"..."}]'`；is_whole/is_solved 评论的 API 错误映射为 `LarkApiError(code="reply_not_allowed")`（Review Focus #4）。
- [ ] **Step 1: 写失败测试** — 两页评论罐头 → 合并升序；字段归一化；add-reply 的 content JSON 结构正确（`[{"type":"text","text":...}]`）；solved 评论回复错误映射。
- [ ] **Step 2–5:** 标准节奏 → commit `feat(mcp): comment list/thread/reply tools`。

### Task 6: FastMCP server 装配

**Files:**
- Create: `feishu-doc-mcp/src/feishu_doc_mcp/server.py`
- Test: `feishu-doc-mcp/tests/test_server.py`

**Interfaces:**
- Produces: `mcp = FastMCP("feishu-doc-mcp")`；注册 Task 2–5 全部函数为 MCP 工具（与 §5 工具名一一对应：`check_environment`/`get_doc_info`/`read_document`/`list_comments`/`get_comment_thread`/`apply_block_operations`/`reply_comment`）；`LarkApiError` 统一序列化为 `{"error":{"code","message","lark_code","hint"}}` 返回（不抛栈给 MCP 客户端）；`main()` 入口（`feishu-doc-mcp` console script，stdio transport）。§5.8：不注册任何其他工具。
- [ ] **Step 1: 写失败测试** — 用 fastmcp `Client(mcp)` in-memory：列出工具恰为 7 个；调用 check_environment（stub）返回结构正确；触发 LarkApiError 的工具调用返回 error dict 且含 hint。
- [ ] **Step 2–5:** 标准节奏 → commit `feat(mcp): FastMCP server assembly`。

### Task 7: skill 包（SKILL.md + 辅助脚本）

**Files:**
- Create: `skill/feishu-doc-cowork/SKILL.md`（frontmatter `name: feishu-doc-cowork` + description「当用户要求对飞书文档做评论驱动的 AI 协同编辑时使用」；正文完整搬入 spec §6 主循环、§6 CLI 调用纪律、§7 git 铁律（含 commit message 模板逐字、空改动守卫、崩溃恢复规则）、§8 并发冲突、§10 已知限制；红线：禁 overwrite/append、禁 --recommend/--domain 授权）
- Create: `skill/feishu-doc-cowork/references/intent-prompt.md`（§9 判定提示词全文：三分类定义、输出 JSON `{verdict, reason, edit_intent_summary}`、输入要素）
- Create: `skill/feishu-doc-cowork/references/scope-checklist.md`（最终 scope 清单 + 每项 `lark-cli schema ...` / `auth check` 复核命令 + 授权命令模板）
- Create: `skill/feishu-doc-cowork/scripts/config_init.py`（生成 §4.1 config.yaml 到 `~/.cache/feishu-doc-cowork/config.yaml`，已存在不覆盖）
- Create: `skill/feishu-doc-cowork/scripts/state.py`（state.json 原子读写：`load(doc_dir)`/`get(doc_dir, cid)`/`upsert(doc_dir, cid, status, **fields)`/`reset_processing(doc_dir)` 崩溃恢复重置为 pending；结构按 §7.5；写用 tmp+rename）
- Create: `skill/feishu-doc-cowork/scripts/git_ops.py`（`ensure_repo(doc_dir)` init+`.gitignore`、`commit_comment(doc_dir, comment_id, comment_text, summary, block_ids, model_name, agent_name, status)` 按 §7.3 模板生成 message 提交全部变更、`has_doc_diff(doc_dir)` 空改动守卫；git 走 subprocess）
- Test: `feishu-doc-mcp/tests/test_skill_scripts.py`（脚本带 `if __name__ == "__main__"` CLI，可被测试 import）

**Interfaces:**
- Produces（供 SKILL.md 主循环引用，也是联调脚本接口）：
  - `state.py`: `load(doc_dir) -> dict`、`upsert(doc_dir, comment_id, status, update_time=None, commit_sha=None, summary=None, error=None)`、`reset_processing(doc_dir) -> list[str]`（返回被重置的 comment_id）。
  - `git_ops.py`: `ensure_repo(doc_dir) -> None`、`has_doc_diff(doc_dir) -> bool`（document.md 与 HEAD 比对）、`commit_comment(...) -> str`（返回 commit sha）。
- [ ] **Step 1: 写失败测试** —
  - state：upsert→load 往返；processing 崩溃恢复 → reset_processing 后状态 pending；并发安全不要求（串行）。
  - git：tmp 目录 ensure_repo → 有 .git 和 .gitignore；写 document.md 后 commit_comment → `git log --format=%B` 含 `[comment:c_1]`、评论全文、`状态: done`、模型/Agent 名；50 字符截断规则（第一行超长时）；连续两评论 → 两个 commit（I1/I2 的本地侧）；document.md 无变化时 has_doc_diff=False（I4 守卫）。
- [ ] **Step 2–5:** 标准节奏 → commit `feat(skill): SKILL.md, state machine and git helpers`。

### Task 8: README 与 MCP 文档

**Files:**
- Create: `README.md`（根）：架构图（用 spec §3）、lark-cli 安装引导（npm `@larksuite/cli`）、MCP 安装（`uv tool install ./feishu-doc-mcp` 或 pip）、skill 安装（拷到 skills 目录）、**最终 scope 清单表**（从 scopes.py 生成，含每项 schema/auth check 复核命令）、授权命令模板（逐 --scope，明示禁 --recommend/--domain）、config.yaml 说明、spec §10 限制全文、联调清单（指向 docs/verification.md）
- Create: `feishu-doc-mcp/README.md`：7 个工具的入参/出参 JSON Schema 表、错误格式 `{error:{code,message,lark_code,hint}}`、LARK_CLI_BIN 环境变量、红线声明（无全量写工具）
- Create: `docs/verification.md`：spec §11 全部用例（U1–U6、P1–P4、I1–I12）的检查表格式，每项留「证据」栏；标注 U/I 中依赖真实授权的项在 Task 9 执行
- [ ] **Step 1:** 写三个文档；scope 表与 scopes.py 逐项 diff 一致（用脚本或人工比对，不一致必改）。
- [ ] **Step 2:** 验证 README 中所有命令真实存在（`lark-cli auth login --help` 等已实测；文档里不许出现未实测的标志）。
- [ ] **Step 3:** Commit `docs: README, MCP reference, verification checklist`。

### Task 9: 联调与验收（**前置阻塞：user 身份重新登录**）

现状实测：`auth status` 显示 user identity `missing (refresh token expired)`，bot ready。spec 要求 `--as user`。**执行前需用户完成：**
`lark-cli auth login --scope "docs:document.comment:read" --scope "docs:document.comment:create" --scope "drive:drive.metadata:readonly" --scope "docx:document:readonly" --scope "docx:document" --scope "board:whiteboard:node:read" --scope "board:whiteboard:node:create" --scope "board:whiteboard:node:update" --scope "board:whiteboard:node:delete"`（device flow，浏览器确认）。

- [ ] **Step 1:** 校准 Review Focus #1–#3：真实 `+fetch --detail with-ids` 输出 → 校准 `BLOCK_ID_PATTERN`；真实 metas 响应 → 校准 owner 字段；真实验证 +update --revision-id 冲突语义。每项改动回写对应测试 stub 数据。
- [ ] **Step 2:** 准备测试文档（含段落、表格、画板），按 docs/verification.md 执行 U1–U6、P1–P4、I1–I12，逐项填证据（git log、CLI 日志、auth status 输出）。
- [ ] **Step 3:** 写测试报告 `docs/test-report.md`；失败的项修复后重跑。
- [ ] **Step 4:** Commit `test: integration verification report`。

## Self-Review 记录

- Spec 覆盖：§4.1 配置 → Task 7 config_init；§4.2/4.3 scope → Task 2 scopes.py + Task 8 README + Task 9 P 用例；§5.1–5.8 → Task 2–6（5.8 由 Task 6「恰为 7 个工具」测试保证）；§6 主循环/git 纪律 → Task 7 SKILL.md + git_ops/state 脚本；§7.5 state.json → Task 7；§8 → Task 4 CONFLICT + SKILL.md 串行规则；§9 → Task 7 references；§10 → Task 8 README；§11 → Task 8 verification.md + Task 9。
- 主循环本身是「agent 读 SKILL.md 后自主执行的工作流」，不是可运行代码——可测试部分（state/git/config）已抽成脚本并有测试，意图判定与轮询节奏由 agent 执行，联调 I8 覆盖常驻行为。
- 类型一致性：`run_lark_cli/unwrap/LarkApiError` 在 Task 1 定义，Task 2–6 只消费；`BlockEntry`/`parse_fetch_output` Task 3 定义 Task 4 消费；脚本接口 Task 7 定义，SKILL.md 引用同名。
