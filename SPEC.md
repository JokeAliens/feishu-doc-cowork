# 飞书文档 AI 协同编辑 Skill + MCP 设计规范

> 版本：v2.0
> 目标读者：负责实现和调试本系统的 AI agent
> 实现栈：Python 3.11+ / FastMCP（薄封装层）/ **lark-cli（@larksuite/cli，API 执行层）** / git

---

## 1. 项目目标

构建一个「Skill + MCP Server」组合，使 AI agent 能够对指定飞书文档进行**评论驱动的增量协同编辑**：

1. 用户提供飞书文档地址后，agent 启动一个**永不主动退出**的常驻工作循环；
2. 循环轮询该文档的评论；
3. 只处理**文档 owner** 发表的评论；
4. 由 agent（LLM）判断评论是否为「修改文档的要求」：

- 是 → 按评论要求，以**块级最小修改**方式在线修改文档（禁止整篇重写上传）；
- 否 → 忽略，不做任何动作、不回复；

5. 每个评论的处理（从读取到修改完成）对应**恰好一个 git commit**，commit message 必须包含评论内容，保证人工仅凭 git log 即可审计每次修改；
6. 修改完成并 commit 后，在该评论下回复固定格式：
`修改完成，使用AI模型：{model_name}， Agent：{agent_name}`
示例：`修改完成，使用AI模型：GLM5.3， Agent：OMP`
7. 唯一的停止方式是人工手动终止 agent 进程（SIGINT/SIGTERM），进程须优雅退出；
8. 飞书侧授权 scope 必须**最小化**：只申请本系统实际用到的 scope，逐个精确授权，禁止 `--recommend` 式宽泛授权。

### 1.1 明确的非目标

- 不做实时协同（OT/CRDT）。飞书开放 API 是 last-writer-wins 模型，本系统按「串行队列 + 写前校验」规避冲突，见 §8。
- 不处理多人协作场景，仅识别文档 owner 的评论。
- v2.0 不做事件订阅（webhook），纯本地轮询。（可选 v2.1：用 `lark-event` skill 的 WebSocket 事件订阅做评论事件的低延迟触发，轮询兜底。）
- 不自建飞书应用、不管理 app_id/app_secret——鉴权完全交给 lark-cli。

---

## 2. 需求决策记录

| # | 决策点 | 裁定 | 理由 |
| --- | --- | --- | --- |
| D1 | API 执行层 | **lark-cli 三层命令体系**：Shortcuts（`+` 前缀）→ API Commands（1:1 端点）→ Raw API（`lark-cli api`，覆盖 2500+ 端点）。块级修改走 Raw API 层 PATCH | 官方维护、AI 友好、JSON 契约稳定；避免重复造轮子 |
| D2 | MCP 定位 | Python + FastMCP 写**薄封装层** feishu-doc-mcp：把 lark-cli 调用包装成结构化 MCP 工具，统一解析 `{ok, data, error}` envelope | 保留 skill+mcp 架构，MCP 只做适配不做业务 |
| D3 | 鉴权 | **lark-cli OAuth 用户身份**（`lark-cli auth login`），凭证存 OS 钥匙串（lark-cli 内建），DPoP 保持默认 `preferred` | 最小权限 + 不碰 app_secret；评论/修改以用户本人身份发出，天然可审计 |
| D4 | 最小权限 | 逐个 scope 精确授权：`lark-cli auth login --scope "xxx"`，**禁用 `--recommend`**；启动时用 `lark-cli auth check` 校验；scope 清单用 `lark-cli schema <method>` 实测确认 | 用户明确要求权限尽量少 |
| D5 | 评论监听 | 纯轮询评论 API，默认间隔 10s ± 20% 抖动 | 用户指定；抖动避免限流误判 |
| D6 | 「文档作者」判定 | 取文档 owner（文件元信息 `owner_id`），与评论者 user_id 比对 | 用户指定 |
| D7 | 修改粒度 | 一律走 docx/v1 块级 API（经 lark-cli Raw API / API Commands 层），**禁止** `docs +update --markdown` 类全量覆盖命令出现在任何写路径 | 原始需求核心 |
| D8 | 能力范围 | 正文块级编辑 + 表格（行列增删、单元格更新）+ **画板（lark-whiteboard DSL 渲染）** | 用户指定；画板能力由 lark-cli 提供 |
| D9 | git 版本目录 | `~/.cache/feishu-doc-cowork/{doc_id}/`，启动时 `git init`（已存在则复用） | 原始需求 |
| D10 | commit 粒度 | **一个评论 = 恰好一个 commit**。一评论内多次块修改合并为一个 commit；多评论严禁合并 | 原始需求 |
| D11 | 评论意图判定 | 由 agent（LLM）判断，MCP/CLI 只提供数据通道 | 保持下层无业务逻辑 |
| D12 | 评论去重与恢复 | 本地持久化 `state.json`，按 `comment_id + update_time` 去重，崩溃重启可续跑 | 必需补充 |
| D13 | 非修改类评论 | 完全忽略，**不回复** | 原始需求明确化 |
| D14 | 修改失败 | 回复评论说明失败原因（格式见 §7.4），标记 failed，不阻塞队列 | 必需补充 |
| D15 | git 操作归属 | git 命令由 skill 通过 shell 执行，不进 MCP | MCP 只做飞书通道 |
| D16 | CLI 输出契约 | 一律 `--format json`，以 `ok == true` + exit code 判成功（**不是** `code == 0`）；写命令先 `--dry-run` 预览再执行 | lark-cli 官方契约，防幻觉写操作 |

---

## 3. 整体架构

```javascript
┌─────────────┐   MCP 协议   ┌────────────────────┐   子进程调用    ┌─────────────────┐
│ Agent(Skill) │ ◄─────────► │  feishu-doc-mcp    │ ─────────────► │   lark-cli      │
│ 主循环/意图判定│             │  (FastMCP 薄封装)   │ ◄───────────── │ Shortcuts/API/  │
└──────┬──────┘             │  无状态、无业务逻辑   │  JSON envelope │ Raw API 三层     │
       │                    └────────────────────┘                └────────┬────────┘
       │ shell(git)                                                        │ HTTPS (OAuth 用户身份,
       ▼                                                                   │  最小 scope, 钥匙串凭证)
┌──────────────────────────────┐                                           ▼
│ ~/.cache/feishu-doc-cowork/  │                                    ┌────────────┐
│   {doc_id}/                  │                                    │ 飞书开放平台 │
│     ├─ .git/                 │                                    └────────────┘
│     ├─ document.md           │ ← 文档内容快照（用于 diff/审计）
│     ├─ block_map.json        │ ← markdown 行 ↔ block_id 映射
│     └─ state.json            │ ← 评论处理状态（被 git 跟踪）
└──────────────────────────────┘
```

**职责划分：**

- **lark-cli**：唯一与飞书开放平台通信的组件。负责鉴权（OAuth + 钥匙串 + DPoP）、API 调用、分页、错误分类。本系统**不得**绕过它直接调 API。
- **feishu-doc-mcp（FastMCP 薄封装）**：把 §5 的工具映射为 lark-cli 子进程调用，解析 envelope、归一化错误、做入参校验。无状态、无缓存、无意图判断。
- **Skill（SKILL.md + 辅助脚本）**：主循环、意图判定、修改规划、git 版本管理、回复规则。
- **git 目录**：审计与回滚基础设施。

**lark-cli 三层命令使用原则**（写进 skill 红线）：

| 层级 | 用途 | 例 |
| --- | --- | --- |
| Shortcuts（`+`） | 只用于**只读**高频操作（如读文档） | `lark-cli docs +read ...`（以实际 `--help` 为准） |
| API Commands | 1:1 端点的结构化操作 | 评论列表、回复评论 |
| Raw API | 块级增量修改的唯一通道 | `lark-cli api PATCH /open-apis/docx/v1/documents/{id}/blocks/{block_id} --data '{...}'` |

---

## 4. 配置与鉴权

### 4.1 配置文件

`~/.cache/feishu-doc-cowork/config.yaml`（首次运行由 skill 引导创建）：

```yaml
runtime:
  poll_interval_sec: 10
  poll_jitter: 0.2
  max_retry_per_comment: 3
  backoff_base_sec: 5                 # 429/5xx 指数退避基数，上限 120s
identity:
  model_name: "GLM5.3"                # 回复格式中的 AI 模型名
  agent_name: "OMP"                   # 回复格式中的 Agent 名
lark_cli:
  binary: "lark-cli"                  # PATH 中的 lark-cli
  identity: "user"                    # 固定 user 身份（--as user）
```

**注意**：配置中**不出现** app_id/app_secret/任何 token——凭证完全由 lark-cli 管理（OS 钥匙串）。

### 4.2 最小权限 scope 清单

> 下表为**候选清单**。实现 agent 必须用 `lark-cli schema <method>` 对每个实际用到的端点逐一核实 scope 名称（schema 命令会返回该方法支持的 identity 与 scope），以实测为准修正本表，并在 README 中固化最终清单。

| 能力 | 用到的端点/命令 | 候选 scope（待 schema 实测确认） |
| --- | --- | --- |
| 读文档块 | `GET /docx/v1/documents/{id}/blocks*` | `docx:document:readonly` |
| 块级写文档 | `PATCH/POST/DELETE /docx/v1/documents/{id}/blocks*` | `docx:document` |
| 读文件元信息（取 owner） | `POST /drive/v1/metas/batch_query` | `drive:drive:readonly`（或更细的 file meta 只读 scope，取 schema 实测中最小者） |
| 读评论 | `GET /drive/v1/files/{token}/comments*` | 评论只读 scope（schema 实测） |
| 回复评论 | `POST /drive/v1/files/{token}/comments/{id}/replies` | 评论写 scope（schema 实测） |
| 画板读写 | lark-whiteboard 对应端点 | 画板读写 scope（schema 实测；若无细分则取画板最小可用 scope） |

**授权命令模板**（skill 引导用户执行，逐域授权，可分多次追加）：

```bash
lark-cli auth login --scope "docx:document:readonly" --scope "docx:document" --scope "<评论读>" --scope "<评论写>" --scope "<meta读>" --scope "<画板>"
```

红线：

- **禁止** `lark-cli auth login --recommend`（会授予宽泛常用 scope 集）；
- **禁止** `--domain` 整域授权（域粒度 > 方法粒度）；
- 若某 scope 有 readonly 变体且只需读，**必须**用 readonly 变体；
- 最终授权集合 = 上表实测清单的并集，一个不多。

### 4.3 启动时权限自检（skill 必做）

```bash
lark-cli auth status                      # 已登录？
for scope in <最终清单>: lark-cli auth check $scope   # 每个 scope exit 0？
```

任一缺失 → 打印精确的补授权命令（单条 `--scope` 追加），等用户完成后重试。**不得**替用户决定放宽 scope。

### 4.4 文档协作者说明

以用户身份运行时，文档权限继承用户本人权限（owner 的文档天然可编辑）。若 agent 实际操作账号与 owner 不同，需确保该账号对文档有可编辑权限，否则 API 返回权限错误时 skill 应明确提示。

---

## 5. MCP Server 工具清单（feishu-doc-mcp）

薄封装原则：**一个 MCP 工具 → 一条或少数几条 lark-cli 调用**；所有命令带 `--format json`；解析 envelope（`ok==true` 为成功）；错误统一映射为 `{ "error": { "code", "message", "lark_code", "hint" } }`（透传 lark-cli 的 `error.hint`，它对 agent 自修复很有价值）；写操作内部先 `--dry-run` 校验参数再真实执行。

### 5.1 `check_environment`

- 行为：执行 `lark-cli auth status` + 对 §4.2 清单逐个 `auth check`。
- 出参：`{ logged_in, missing_scopes: [...], suggested_login_command }`

### 5.2 `get_doc_info`

- 入参：`doc_url`（完整 URL 或纯 token）
- 行为：解析 URL 得 `doc_token`/`doc_type`（支持 `docx`；旧版 `doc` 报错提示迁移；`wiki` 链接先用 wiki 命令解析出实际 obj_token）；经 lark-cli 调文件元信息接口取 `owner_id`、标题。
- 出参：`{ doc_id, doc_type, title, owner_id }`

### 5.3 `read_document`

- 入参：`doc_id`
- 行为：经 lark-cli 拉全量块（`--page-all` 自动分页），转换为带行号 markdown + `block_map`（行 ↔ `block_id`、块类型、父块、children index）。画板块读出为 DSL 描述（lark-whiteboard 能力），图片/附件块记录 token。
- 出参：`{ markdown, block_map, revision_id }`
- 要求：转换**可逆寻址**——agent 能据 markdown 精确定位 block_id 与 index，这是增量修改的基础。

### 5.4 `list_comments`

- 入参：`doc_id`、`is_solved`（默认 false）
- 行为：经 lark-cli（API Commands 层评论命令，无对应命令则用 Raw API `GET /drive/v1/files/{token}/comments?file_type=docx`）拉取评论，`--page-all` 分页。每条含：`comment_id`、`user_id`、`create_time`、`update_time`、`content`、`quote`、`reply_count`。
- 出参：按 `create_time` 升序数组。

### 5.5 `get_comment_thread`

- 入参：`doc_id`、`comment_id`
- 行为：拉取该评论全部回复，出参完整线程（意图判定与修改规划基于线程整体，而非首条）。

### 5.6 `apply_block_operations`

- 入参：`doc_id`、`operations: [...]`、`expected_revision_id`（冲突检测，见 §8）
- 行为：把操作**按序翻译**为 lark-cli Raw API 块级调用。支持的操作：

| op 类型 | 说明 | lark-cli 通道（Raw API 端点） |
| --- | --- | --- |
| `update_text` | 更新指定 block 文本元素 | `PATCH /docx/v1/documents/{id}/blocks/{block_id}` |
| `insert_blocks` | 指定父块指定 index 插入新块 | `POST /docx/v1/documents/{id}/blocks/{parent_id}/children`（带 index） |
| `delete_blocks` | 删除父块下 [start, end) 区间 | `DELETE /docx/v1/documents/{id}/blocks/{parent_id}/children/batch_delete` |
| `replace_block` | delete + insert 组合 | 组合 |
| `update_table_cells` | 批量更新表格单元格 | 逐 cell block `PATCH` |
| `table_insert_rows` / `table_insert_columns` | 表格行列增删 | table block 的 children 接口（table 专用参数） |
| `update_board` | 画板块内容修改（DSL 描述） | lark-whiteboard 对应命令/端点；不支持的具体图元返回 `BOARD_UNSUPPORTED` |

- 出参：每 op 执行结果数组 + 最新 `revision_id`。
- 硬性红线：**任何一次调用产生的写请求数 ≤ 操作数 + 1**；实现中禁止出现「拉全文 → 重建 → 全量覆盖」路径；**禁止**调用任何 `+update` / `--overwrite` 类全量命令。代码评审红线。
- 每个写请求先 `--dry-run` 本地校验，再真实执行（dry-run 输出进调试日志）。

### 5.7 `reply_comment`

- 入参：`doc_id`、`comment_id`、`content`
- 行为：经 lark-cli 调 `POST /drive/v1/files/{token}/comments/{id}/replies`。
- 注意：以用户身份发出，回复人显示为用户本人——这正是预期（审计友好）。

### 5.8 明确不提供的工具

- 不提供「全量替换文档」工具（接口层杜绝整篇上传）。
- 不提供 git 工具（D15）。
- 不转发与本文档无关的 lark-cli 能力（im/calendar/mail 等）——MCP 攻击面最小化，与最小权限原则一致。

---

## 6. Skill 主循环工作流（写进 SKILL.md）

```javascript
启动：
  1. 读取 config.yaml；缺失/非法 → 报错退出
  2. check_environment：
     未登录 → 输出 lark-cli 安装/登录引导（config init → auth login --scope 精确清单），退出
     缺 scope → 输出精确补授权命令，退出
  3. get_doc_info(doc_url) → doc_id, owner_id
  4. 确保 ~/.cache/feishu-doc-cowork/{doc_id}/ 存在且 git init（已有 .git 则复用）
  5. read_document → 写入 document.md + block_map.json
     若仓库为空 → 首个 commit: "init: 文档基线快照 (doc: {title})"
  6. 加载 state.json（无则初始化空）
  7. 进入主循环

主循环（永久，直到 SIGINT/SIGTERM）：
  1. sleep(poll_interval × (1 ± jitter))
  2. list_comments(doc_id, is_solved=false)
  3. 过滤：
     a. user_id == owner_id（非 owner 一律跳过）
     b. comment_id 不在 state.json，或 state 中 update_time < 当前 update_time
        （owner 编辑/追加过评论 → 视为新需求重新处理）
  4. 对每条候选评论，串行执行（严禁并行，见 §8）：
     a. 标记 processing，落盘 state.json
     b. get_comment_thread → LLM 意图判定：
        - 「修改要求」→ 继续
        - 「提问/讨论/闲聊/超范围」→ 标记 skipped，落盘，不回复，下一条
     c. 快照：read_document → doc_before.md（记录 revision_id）
     d. 规划：基于 markdown + block_map 生成 operations（块级最小修改）
     e. apply_block_operations（带 expected_revision_id；CONFLICT 时重规划，上限 3 次）
     f. 验证：再次 read_document → doc_after.md，确认目标改动生效
     g. git 版本管理（规则见 §7）：更新 document.md / block_map.json / state.json → 恰好一个 commit
     h. reply_comment("修改完成，使用AI模型：{model_name}， Agent：{agent_name}")
     i. 标记 done，落盘
     j. 任何异常 → 捕获、标记 failed（含原因）、回复失败说明、继续下一条
  5. 回到 1
```

**信号处理**：SIGINT/SIGTERM 时，若无评论在 processing 则立即退出；若有，完成该评论的「commit+回复」或「标记 failed」后再退出。退出前打印本次会话统计（done/skipped/failed）。

**CLI 调用纪律**（写进 skill）：

- 所有 lark-cli 调用带 `--format json`；判成功看 `ok == true` / exit code，**不是** `code == 0`；
- 分页用 `--page-all`，页间 `--page-delay 500`；
- 写操作先 `--dry-run`；
- 遇到权限错误 → 用 `lark-cli schema <method>` 查所需 scope，输出精确补授权命令后进入 failed 流程，**不得**自行换更宽的 scope。

---

## 7. Git 版本管理规范

### 7.1 目录与文件

`~/.cache/feishu-doc-cowork/{doc_id}/`：

| 文件 | git 跟踪 | 说明 |
| --- | --- | --- |
| `document.md` | 是 | 文档全文快照，每 commit 更新 |
| `block_map.json` | 是 | 块映射，与 document.md 同步 |
| `state.json` | 是 | 评论状态机，随对应评论的 commit 一起提交 |
| `.gitignore` | 是 | 至少忽略 `*.tmp`、`__pycache__/` |

### 7.2 Commit 粒度铁律

- **一个评论 = 恰好一个 commit**，包含该评论处理产生的全部文件变更。
- 一评论内无论多少次 `apply_block_operations`，只产生一个 commit。
- 多评论严禁合并为一个 commit。
- **空改动守卫**：doc_after 与 doc_before 无 diff → 不 commit，回复「内容已符合要求，无需修改」，状态 done。
- 基线 init commit 不计入评论 commit。

### 7.3 Commit message 格式

```javascript
[comment:{comment_id}] {评论内容第一行，截断至 50 字符}

评论全文:
{评论完整内容，含线程中 owner 的追问}

处理摘要:
{agent 用 1-3 句话描述实际做了什么修改}

修改块: {block_id 列表，逗号分隔}
AI模型: {model_name} / Agent: {agent_name}
状态: done
```

要求：`git log --oneline` 一眼看出「哪个评论、要干什么」；`git log -p` 能看到完整文档 diff。审计场景**不允许**出现 "update"、"fix" 类无语义 message。

### 7.4 失败回复格式

```javascript
修改未完成：{失败原因简述}
使用AI模型：{model_name}， Agent：{agent_name}
```

### 7.5 state.json 结构

```json
{
  "doc_id": "xxx",
  "comments": {
    "c_123456": {
      "status": "done",
      "update_time": 1739000000,
      "commit_sha": "a1b2c3d",
      "summary": "把第三章标题改为...",
      "error": null,
      "updated_at": 1739000100
    }
  }
}
```

崩溃恢复：重启发现 `processing` 状态的评论 → 重置为 pending 重新处理；重处理前必须重新 read_document 并重新规划，**禁止**复用崩溃前的 operations。

---

## 8. 并发与冲突控制

1. **串行队列**：同一文档同一时刻只处理一条评论，无并行 worker。
2. **写前校验**：规划时记录 revision_id；`apply_block_operations` 携带 `expected_revision_id`，MCP 侧执行前重新拉文档信息比对 revision（或抽样比对目标 block 内容哈希），不一致返回 `CONFLICT`。
3. **冲突重试**：skill 收到 `CONFLICT` → 重新 read_document + 重新规划，上限 3 次，仍失败则标记 failed 并回复。
4. **人机同时编辑**是已知风险（last-writer-wins），README 明确告知：尽量避免在 agent 处理时编辑同一文档。

---

## 9. 评论意图判定提示词（skill 内置）

LLM 判定输入：评论内容 + quote（被引用原文）+ 线程上下文 + 文档相关段落。三选一：

- `EDIT_REQUEST`：明确增/删/改文档内容（含画板、表格）→ 执行；
- `QUESTION_OR_DISCUSS`：提问、讨论、表态 → skipped，不动作；
- `OUT_OF_SCOPE`：是修改要求但超出能力（如插入附件、改权限）→ skipped，不动作（v2.0 静默，避免评论噪音）。

输出结构化 JSON：`{ "verdict", "reason", "edit_intent_summary" }`，`edit_intent_summary` 复用于 commit message「处理摘要」。

---

## 10. 已知限制（写进交付 README）

1. 轮询制，评论感知延迟 = poll_interval（默认 10s）+ 处理耗时，非实时。（v2.1 可评估 lark-event WebSocket 订阅评论事件做低延迟触发，轮询兜底。）
2. 画板编辑能力以 lark-whiteboard DSL 覆盖面为准；DSL 无法表达的图元修改返回 `BOARD_UNSUPPORTED`，按 OUT_OF_SCOPE 处理。
3. 旧版 `doc`（非 docx）无块级 API，启动时检测并明确拒绝；wiki 链接先解析再处理。
4. API 无协同感知，人机同改同一段落存在覆盖风险。
5. 评论「解决」（is_solved=true）后默认不再处理；owner 重新编辑已 done 的评论会触发重新处理（D12 的 update_time 机制）。
6. 回复以用户本人身份发出（OAuth 用户身份），在文档评论区看起来是"自己回复自己"，属预期行为。

---

## 11. 调试与验收标准

准备：测试文档 + 已按 §4.2 精确授权的 lark-cli。全部通过才算完成。

### 11.1 单元级

| 用例 | 预期 |
| --- | --- |
| U1 URL 解析 | 支持 `https://xxx.feishu.cn/docx/{token}?xxx`、纯 token、wiki 链接；旧 doc 链接报明确错误 |
| U2 read_document 可逆寻址 | 随机抽 10 个 markdown 段落，能通过 block_map 找到正确 block_id |
| U3 最小修改 | 只改 1 句话，日志确认只发出 1 个 PATCH block 请求，无全量写、无 `+update` 类命令 |
| U4 评论过滤 | 非 owner 评论不进入处理流程 |
| U5 意图判定 | 10 条样本（5 修改/3 提问/2 超范围），判定准确率人工确认 |
| U6 envelope 解析 | 模拟 lark-cli 错误输出（`ok:false` + hint），MCP 错误映射正确且 hint 透传 |

### 11.2 权限最小化验收

| 用例 | 预期 |
| --- | --- |
| P1 精确授权 | 全程未使用 `--recommend` / `--domain`；授权命令只含 §4.2 最终清单的 scope |
| P2 scope 自检 | 人为 revoke 一个 scope 后启动 → skill 报出精确的补授权命令（单 scope），不代用户放宽 |
| P3 清单可复核 | README 中固化最终 scope 清单，且每个 scope 可经 `lark-cli schema` 复核到具体端点 |
| P4 无超配 | `lark-cli auth status` 显示的已授 scope 集合 == README 清单，一个不多 |

### 11.3 集成级（git 铁律）

| 用例 | 预期 |
| --- | --- |
| I1 单评论多修改 | 一条评论要求改 3 处 → git log 只新增 **1** 个 commit，含全部 3 处 diff |
| I2 多评论 | 连续 3 条修改评论 → **3** 个 commit，顺序与评论时间一致，互不包含对方改动 |
| I3 commit message | `git log --oneline` 人工检查通过；message 含评论全文与模型/Agent 名 |
| I4 空改动 | 评论要求「把 X 改成 X」（已是目标状态）→ 无 commit，回复说明 |
| I5 崩溃恢复 | 处理中 kill -9 → 重启后该评论被重新正确处理，无重复 commit、无重复回复 |
| I6 冲突 | 处理期间人工在浏览器改同一 block → 触发 CONFLICT 重试，最终正确或 failed，不产生错误内容 commit |
| I7 非修改评论 | owner 发提问评论 → 无 commit、无回复，状态 skipped |
| I8 常驻与退出 | 30 分钟无评论不退出；SIGINT 优雅退出并打印统计 |
| I9 重复评论编辑 | owner 编辑已 done 的评论 → 重新处理并产生新 commit |
| I10 回复格式 | 成功回复精确匹配 `修改完成，使用AI模型：X， Agent：Y`（注意中文标点与空格与示例一致） |
| I11 画板 | 评论要求修改画板内容 → 经 lark-whiteboard 通道完成，commit 与回复符合铁律；DSL 不支持时按 OUT_OF_SCOPE |
| I12 表格 | 评论要求改表格（增行/改单元格）→ 只发表格相关块级请求，无整表重建 |

### 11.4 交付物清单

1. `feishu-doc-mcp/`：FastMCP 薄封装源码（pyproject、README、工具 JSON Schema）
2. skill 包：`SKILL.md`（含 §6 主循环、§7 git 规范、§9 判定提示词、§6 CLI 调用纪律）+ 辅助脚本
3. README：lark-cli 安装引导、**最终最小 scope 清单（含 schema 复核方法）**、限制说明
4. 测试报告：上述用例逐项结果与证据（git log、CLI 调用日志、auth status 输出）

---

## 12. 实现顺序（里程碑）

1. M0：lark-cli 安装 + `config init` + 精确 scope 登录 + `auth status`/`auth check` 自检打通（验证 P1–P4）
2. M1：feishu-doc-mcp 骨架 + envelope 解析 + `check_environment` / `get_doc_info` / `read_document`（验证 U1/U2/U6）
3. M2：`apply_block_operations` 全 op 类型（验证 U3，红线：无全量写路径、无全量命令）
4. M3：`list_comments` / `get_comment_thread` / `reply_comment`（验证 U4）
5. M4：skill 主循环 + 意图判定 + state.json（验证 U5、I7）
6. M5：git 版本管理全套规则（验证 I1–I4、I9、I10）
7. M6：冲突重试、崩溃恢复、优雅退出（验证 I5、I6、I8）
8. M7：表格 + 画板通道（验证 I11、I12）
9. M8：文档与测试报告交付