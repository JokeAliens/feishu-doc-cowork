# feishu-doc-cowork

飞书文档 AI 协同编辑系统：Skill + MCP Server。AI agent 轮询指定飞书 docx 文档的 **owner 评论**，判定修改意图后以**块级最小修改**在线编辑文档，每条评论对应**恰好一个 git commit**，完成后回复评论。设计规范见 [SPEC.md](SPEC.md)。

## 架构

```mermaid
flowchart LR
    A["Agent (Skill)<br/>主循环/意图判定/git"] <-->|MCP 协议| B["feishu-doc-mcp<br/>FastMCP 薄封装，无状态"]
    B -->|子进程, JSON envelope| C["lark-cli<br/>Shortcuts / API Commands / Raw API"]
    C -->|HTTPS, OAuth 用户身份, 最小 scope| D["飞书开放平台"]
    A -->|shell| E["~/.cache/feishu-doc-cowork/{doc_id}/<br/>.git + document.md + block_map.json<br/>+ state.json + backups/"]
```

- **lark-cli** 是唯一飞书通道（鉴权、分页、错误分类）；本系统不绕过它直调 API。
- **feishu-doc-mcp** 只做适配：envelope 解析、错误归一化、入参校验；无业务逻辑。
- **Skill**（`skill/feishu-doc-cowork/SKILL.md`）承载主循环、意图判定、git 铁律。
- **git 目录**是审计与回滚基础设施；启动时做**纯本地备份**（保留 3 份，SPEC D17）。

## 安装

前置：Python ≥ 3.11（推荐 uv 管理）、Node.js（装 lark-cli）、git。

```bash
# 1. lark-cli（@larksuite/cli）
npm install -g @larksuite/cli
lark-cli config init          # 按提示绑定应用

# 2. 精确授权（禁止 --recommend / --domain；清单见下）
lark-cli auth login \
  --scope "docs:document.comment:read" \
  --scope "docs:document.comment:create" \
  --scope "drive:drive.metadata:readonly" \
  --scope "docx:document:readonly" \
  --scope "docx:document" \
  --scope "board:whiteboard:node:read" \
  --scope "board:whiteboard:node:create" \
  --scope "board:whiteboard:node:delete"

# 3. MCP server
cd feishu-doc-mcp && uv sync   # 或 uv tool install ./feishu-doc-mcp

# 4. skill 包：把 skill/feishu-doc-cowork/ 拷入你的 agent skills 目录

# 5. 运行配置（首次）
python skill/feishu-doc-cowork/scripts/config_init.py
# 编辑 ~/.cache/feishu-doc-cowork/config.yaml 里的 identity.model_name / agent_name
```

MCP client 配置（stdio）：command = `feishu-doc-mcp`（或 `uv run --directory <repo>/feishu-doc-mcp feishu-doc-mcp`）。

## 最小权限 scope 清单（schema/auth 实测 2026-10-12）

单一事实源：[`feishu-doc-mcp/src/feishu_doc_mcp/scopes.py`](feishu-doc-mcp/src/feishu_doc_mcp/scopes.py)；复核方法见 [`skill/feishu-doc-cowork/references/scope-checklist.md`](skill/feishu-doc-cowork/references/scope-checklist.md)。

| scope | 能力 | 复核 |
| --- | --- | --- |
| `docs:document.comment:read` | 读评论 | `lark-cli schema drive.file.comments.list` |
| `docs:document.comment:create` | 回复评论 | `lark-cli schema drive.file.comment.replys.create` |
| `drive:drive.metadata:readonly` | 文件元信息（owner） | `lark-cli schema drive.metas.batch_query` |
| `docx:document:readonly` | 读文档块 | `lark-cli auth check --scope "..."` |
| `docx:document` | 块级写文档 | 同上 |
| `board:whiteboard:node:read` / `:create` / `:delete` | 画板读写 | `lark-cli auth scopes --json`（该应用无 node:update） |

无超配验收：`lark-cli auth status --json` 中本系统用到的 scope == 上表，一个不多。

## 已知限制（SPEC §10）

1. 轮询制，评论感知延迟 = poll_interval（默认 10s）+ 处理耗时，非实时。
2. 画板编辑以 whiteboard DSL 覆盖面为准；无法表达的图元返回 `BOARD_UNSUPPORTED`，按 OUT_OF_SCOPE 静默跳过。
3. 旧版 `doc`（非 docx）无块级 API，启动检测并拒绝；wiki 链接自动解包。
4. 飞书 API 无协同感知（last-writer-wins）；**请尽量避免在 agent 处理时人工编辑同一文档**（冲突有 revision 检测兜底，重试 3 次后标记 failed）。
5. 评论「解决」后默认不再处理；owner 重新编辑已 done 的评论会触发重新处理。
6. 回复以用户本人身份发出，评论区显示"自己回复自己"，属预期（审计友好）。
7. 备份为纯本地快照（保留 3 份）；应用未启用文件删除 scope，不做云盘副本。

## 验证

- 单元测试（stub lark-cli，无需授权）：`cd feishu-doc-mcp && uv run pytest tests/`
- 联调验收清单（需真实授权 + 测试文档）：[docs/verification.md](docs/verification.md)
