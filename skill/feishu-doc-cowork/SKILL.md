---
name: feishu-doc-cowork
description: 当用户要求对指定飞书文档做「评论驱动的 AI 协同编辑」（轮询文档 owner 评论、块级增量修改、git 审计、回复评论）时使用。需要 lark-cli 已登录且配套 feishu-doc-mcp 已安装。
---

# 飞书文档 AI 协同编辑

对指定飞书 docx 文档执行**评论驱动的增量协同编辑**：轮询 owner 评论 → 判定修改意图 → 块级最小修改 → 一评论一 commit → 回复评论。主循环**永不主动退出**，唯一停止方式是 SIGINT/SIGTERM。

配套组件：`feishu-doc-mcp`（MCP 工具，薄封装 lark-cli）+ 本目录 `scripts/`（state/git/backup/config 辅助脚本）。

## 红线（违反即失败）

1. **禁止全量写**：任何写路径不得出现 `overwrite` / `append` / `--overwrite` / 整篇重建上传。只允许块级操作（`str_replace` / `block_*` / docx 块 Raw API / whiteboard +update 不带 --overwrite）。
2. **授权最小化**：禁止 `lark-cli auth login --recommend` / `--domain`；只用 `references/scope-checklist.md` 清单逐个 `--scope` 授权。
3. **一评论 = 恰好一个 commit**；多评论严禁合并；空改动不 commit。
4. **串行处理**：同一时刻只处理一条评论，禁止并行 worker。
5. 身份固定 `--as user`（lark-cli 默认 auto 已满足，不要显式切 bot）。
6. 所有 lark-cli 调用带 `--format json`，判成功看 envelope `ok == true` + exit code，**不是** `code == 0`；写操作 MCP 内部已先 `--dry-run`。

## 启动流程

1. 读配置 `~/.cache/feishu-doc-cowork/config.yaml`；不存在 → 运行 `python scripts/config_init.py` 创建后请用户确认 `identity.model_name` / `agent_name`，再启动。配置非法 → 报错退出。
2. MCP `check_environment`：
   - 未登录 → 输出引导（安装 lark-cli → `lark-cli auth login <精确 scope 清单>`，见 `references/scope-checklist.md`），退出等用户完成。
   - 缺 scope → 输出返回的 `suggested_login_command`（只含缺失项），退出。**不得**自行放宽 scope。
3. MCP `get_doc_info(doc_url)` → `doc_id, owner_id, title`。旧版 doc 链接会报错，提示用户迁移 docx。
4. `python scripts/git_ops.py {doc_dir} ensure-repo`，doc_dir = `~/.cache/feishu-doc-cowork/{doc_id}/`（已存在则复用）。
5. MCP `read_document(doc_id)` → 写入 `document.md` + `block_map.json`。
6. **本地备份（D17）**：`python scripts/backup.py {doc_dir} {doc_id} {title} {revision_id}` 生成 `backups/{ts}/` 快照 + 更新 `backups.json`（只保留最新 3 份，自动删最旧）→ git 提交一次：`backup: 启动本地快照 (doc: {title}, revision: {revision_id})`。
7. 若仓库无任何 commit → 基线 commit：`init: 文档基线快照 (doc: {title})`（备份 commit 与基线 commit 可合并为一次 add，但 message 分行写清两件事；严格起见分两个 commit 亦可）。
8. `python scripts/state.py {doc_dir} reset-processing`（崩溃恢复：processing → pending，重处理前必须重新 read_document + 重新规划，禁止复用旧 operations）。
9. 进入主循环。

## 主循环（永久，直到 SIGINT/SIGTERM）

```
1. sleep(poll_interval_sec × (1 ± poll_jitter))          # 默认 10s ± 20%
2. list_comments(doc_id, is_solved=false)
3. 过滤：
   a. user_id == owner_id（非 owner 一律跳过）
   b. comment_id 不在 state.json，或 state.update_time < 评论当前 update_time
      （owner 编辑过已处理评论 → 视为新需求重新处理）
4. 对每条候选评论，串行执行：
   a. state upsert processing（落盘）
   b. get_comment_thread → 按 references/intent-prompt.md 判定：
      - EDIT_REQUEST → 继续
      - QUESTION_OR_DISCUSS / OUT_OF_SCOPE → upsert skipped，不回复，下一条
   c. 快照：read_document → 保存 doc_before（记录 revision_id）
   d. 规划：基于 markdown + block_map 生成块级最小 operations
   e. apply_block_operations(doc_id, operations, expected_revision_id)
      - CONFLICT → 重新 read_document + 重新规划，上限 3 次；仍失败走 j
   f. 验证：再次 read_document → doc_after，确认目标改动生效
   g. git：更新 document.md / block_map.json / state.json；
      has_doc_diff 为 false（空改动）→ 不 commit，回复「内容已符合要求，无需修改」，upsert done，下一条；
      否则 commit_comment（恰好一个 commit，message 模板见下）
   h. reply_comment("修改完成，使用AI模型：{model_name}， Agent：{agent_name}")
   i. upsert done（含 commit_sha、summary）
   j. 任何异常 → upsert failed（含原因），回复失败格式（见下），继续下一条
5. 回到 1
```

回复格式（逐字，注意中文逗号与空格）：

- 成功：`修改完成，使用AI模型：{model_name}， Agent：{agent_name}`
- 失败：`修改未完成：{失败原因简述}\n使用AI模型：{model_name}， Agent：{agent_name}`

## Commit message 模板（§7.3，逐字）

```
[comment:{comment_id}] {评论内容第一行，截断至 50 字符}

评论全文:
{评论完整内容，含线程中 owner 的追问}

处理摘要:
{1-3 句话描述实际修改}

修改块: {block_id 列表，逗号分隔}
AI模型: {model_name} / Agent: {agent_name}
状态: done
```

禁止 "update"、"fix" 类无语义 message。`git log --oneline` 必须一眼看出「哪个评论、要干什么」。

## 信号处理

SIGINT/SIGTERM：无评论在 processing → 立即退出；有 → 完成该评论的「commit+回复」或「标记 failed」后再退出。退出前打印会话统计（done/skipped/failed 计数）。

## 冲突与降级

- CONFLICT 重试上限 3 次（§8）。
- 权限错误 → 用 `lark-cli schema <method>` 查所需 scope，输出精确补授权命令后走 failed 流程，**不得**自行换更宽 scope。
- 画板修改超出 DSL 能力 → MCP 返回 BOARD_UNSUPPORTED → 按 OUT_OF_SCOPE 处理（skipped，不回复）。
- 429/5xx → 指数退避（base 5s，上限 120s），单评论重试上限 `max_retry_per_comment`（默认 3）。

## 能力范围

正文块级编辑（str_replace / block_replace / block_insert_after / block_delete / block_move_after）+ 表格（行列增删、单元格更新）+ 画板（whiteboard DSL）。超范围（插入附件、改权限等）→ OUT_OF_SCOPE，静默跳过。
