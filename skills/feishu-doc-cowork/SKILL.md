---
name: feishu-doc-cowork
description: 当用户要求对指定飞书文档做「评论驱动的 AI 协同编辑」（轮询文档 owner 评论、块级增量修改、git 审计、回复评论）时使用。需要 lark-cli 已登录且配套 core 包（`cowork` CLI）已安装。
---

# 飞书文档 AI 协同编辑

对指定飞书 docx 文档执行**评论驱动的增量协同编辑**：轮询 owner 评论 → 判定修改意图 → 块级最小修改 → 一评论一 commit → 回复评论。主循环**永不主动退出**，唯一停止方式是 SIGINT/SIGTERM。

配套组件：`core/` 包的 `cowork` CLI（薄封装 lark-cli，输出 JSON 契约）+ 本目录 `scripts/`（state/git/backup/config/poll 辅助脚本）。

## 红线（违反即失败）

1. **禁止全量写**：任何写路径不得出现 `overwrite` / `append` / `--overwrite` / 整篇重建上传。只允许块级操作（`str_replace` / `block_*` / docx 块 Raw API / whiteboard +update 不带 --overwrite）。
2. **授权最小化**：禁止 `lark-cli auth login --recommend` / `--domain`；只用 `references/scope-checklist.md` 清单逐个 `--scope` 授权。
3. **一评论 = 恰好一个 commit**；多评论严禁合并；空改动不 commit。
4. **串行处理**：同一时刻只处理一条评论，禁止并行 worker。
5. 身份固定 `--as user`（lark-cli 默认 auto 已满足，不要显式切 bot）。
6. 所有飞书读写一律经 `cowork` 子命令（内部调 lark-cli `--json`，判成功看 envelope `ok == true` + exit code，**不是** `code == 0`；写操作内部已先 `--dry-run`）。不得绕过 `cowork` 直接调 lark-cli 写文档。

## 启动流程

1. 读配置 `~/.cache/feishu-doc-cowork/config.yaml`；不存在 → 运行 `python scripts/config_init.py` 创建（默认值即可用，无需手改）。配置非法 → 报错退出。
   - **model_name / agent_name 不在配置中**：由署名探测步骤（见第 10 步）产生并落盘 state.json，回复/commit 时从 state.json 读取。
2. `cowork check-environment`：
   - 未登录 → 输出引导（安装 lark-cli → `lark-cli auth login <精确 scope 清单>`，见 `references/scope-checklist.md`），退出等用户完成。
   - 缺 scope → 输出返回的 `suggested_login_command`（只含缺失项），退出。**不得**自行放宽 scope。
3. `cowork get-doc-info <doc_url>` → `doc_id, owner_id, title`。旧版 doc 链接会报错，提示用户迁移 docx。
4. `python scripts/git_ops.py {doc_dir} ensure-repo`，doc_dir = `~/.cache/feishu-doc-cowork/{doc_id}/`（已存在则复用）。
5. `cowork read-document <doc_id>` → 写入 `document.md` + `block_map.json`。
6. **本地备份（D17）**：`python scripts/backup.py {doc_dir} {doc_id} {title} {revision_id}` 生成 `backups/{ts}/` 快照 + 更新 `backups.json`（只保留最新 3 份，自动删最旧）→ git 提交一次：`backup: 启动本地快照 (doc: {title}, revision: {revision_id})`。
7. 若仓库无任何 commit → 基线 commit：`init: 文档基线快照 (doc: {title})`（备份 commit 与基线 commit 可合并为一次 add，但 message 分行写清两件事；严格起见分两个 commit 亦可）。
8. `python scripts/state.py {doc_dir} reset-processing`（崩溃恢复：processing → pending，重处理前必须重新 read_document + 重新规划，禁止复用旧 operations）。
9. **监听确认（强制，不得跳过）**：启动完成后、进入主循环前，必须向用户明确输出并确认：
   > 启动完成：文档《{title}》（{doc_id}），基线 revision {n}，备份已存（保留 3 份）。
   > 我将开始**常驻轮询监听**该文档的评论（每 {poll_interval_sec}s，仅处理你的评论，修改类评论会直接改文档并回复）。确认开始监听吗？

   用户确认 → 进入主循环并启动 watcher；用户拒绝/要求调整 → 按用户指示，**不得**自行开始监听。若宿主不支持交互提问，则以显著消息声明上述内容后直接开始，并在首条回复中再次声明监听状态。
10. **署名探测（每次启动/重启 watcher 必做）**：用户确认监听后，立即自问「**我当前运行的是什么模型**」——依据当前这轮上下文中的模型标识（如系统提示的 `Model:` 字段）作答，agent_name 取当前 agent 框架名。将答案写入 state.json：
    `python scripts/state.py {doc_dir} set-identity "<model_name>" "<agent_name>"`
    - 回复与 commit 的署名**一律读 state.json 的 identity**，禁止凭记忆/印象现编；
    - **每次 watcher 重启（含中断恢复、模型切换后重连）都重做本步**，使署名跟随真实模型变化；
    - 若上下文中找不到模型标识 → 向用户询问一次「当前是什么模型」，以用户回答为准落盘；
    - 诚实兜底：弱模型可能自报错误，用户随时可指出更正，更正后立即 set-identity 覆盖。
11. 进入主循环。

## 主循环（永久，直到 SIGINT/SIGTERM）

**实现方式（强制）**：后台运行 `python scripts/poll_comments.py {doc_id} {owner_id} {poll_interval_sec} {poll_jitter}` 作为 watcher——它发现候选评论后打印 JSON 并退出，你随即处理；**处理完必须立即重新启动 watcher**（watcher 退出 = 监听中断，属异常状态，需向用户声明）。watcher 运行期间向用户明确「监听中」，被停止（SIGINT/SIGTERM/用户要求）时打印会话统计并声明「监听已停止」。

```
1. watcher 发现候选评论（poll_comments.py 每 poll_interval ± jitter 轮询一次）
2. 过滤（已在 poll_comments.py 内完成）：
   a. user_id == owner_id（非 owner 一律跳过）
   b. comment_id 不在 state.json，或 state.update_time < 评论当前 update_time
      （owner 编辑过已处理评论 → 视为新需求重新处理）
3. 对每条候选评论，串行执行：
   a. state upsert processing（落盘）
   b. `cowork get-comment-thread` → 按 references/intent-prompt.md 判定：
      - EDIT_REQUEST → 继续
      - QUESTION_OR_DISCUSS / OUT_OF_SCOPE → upsert skipped，不回复，下一条
   c. 快照：`cowork read-document` → 保存 doc_before（记录 revision_id）
   d. 规划：基于 markdown + block_map 生成块级最小 operations
   e. `cowork apply-ops <doc_id> --ops @ops.json --expected-revision N`
      - CONFLICT → 重新 read-document + 重新规划，上限 3 次；仍失败走 k
   f. 验证：再次 `cowork read-document` → doc_after，确认目标改动生效
   g. state upsert done（summary、error=null；commit_sha 暂留空）→ 落盘
   h. git：更新 document.md / block_map.json；
      has_doc_diff 为 false（空改动）→ 不 commit，`cowork reply`「内容已符合要求，无需修改」，`cowork resolve` 后下一条；
      否则 commit_comment（恰好一个 commit，message 模板见下；git add -A 会把 g 的 state.json 一并纳入本评论的 commit）
   i. commit 后 upsert commit_sha
   j. `cowork reply <doc_id> <comment_id> "修改完成，使用AI模型：{model_name}， Agent：{agent_name}"`
      → 随后重新 `cowork get-comment-thread` 取**回复后**的最新 update_time 并 upsert 覆盖 state
      （自己的回复会 bump 评论 update_time；不刷新则下一轮 poll 误判 owner 编辑过而无限重处理——2026-10-12 实测确认）
      → 最后 `cowork resolve`（标记解决并隐藏，评论闭环；solved 评论不再进入轮询）
   k. 任何异常 → upsert failed（含原因；若 apply-ops 返回 PartialApplyError（error.code=底层原因、message 含已应用列表），失败回复必须列出其 applied 列表——「已应用前 N 项（块 x,y），失败于块 z」），回复失败格式（见下），继续下一条
4. 重新武装 watcher（见上方「实现方式」），回到 1
```

> **commit_sha 自引用裁定**：一条评论的 commit 不可能包含自己的 sha。顺序定为「先 upsert done（无 sha）→ commit → 补 sha」；补 sha 的尾随 state.json 变更随下一个 commit 归档（或会话退出时）。审计以 git log 为准，state.json 的 sha 字段仅为索引便利。failed/skipped 的 state 变更同理。

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
- 画板修改超出 DSL 能力 → apply-ops 结果标 BOARD_UNSUPPORTED → 按 OUT_OF_SCOPE 处理（skipped，不回复）。
- 429/5xx → 指数退避（base 5s，上限 120s），单评论重试上限 `max_retry_per_comment`（默认 3）。

## 能力范围

正文块级编辑（str_replace / block_replace / block_insert_after / block_delete / block_move_after）+ 表格（行列增删、单元格更新）+ 画板（whiteboard DSL）。超范围（插入附件、改权限等）→ OUT_OF_SCOPE，静默跳过。
