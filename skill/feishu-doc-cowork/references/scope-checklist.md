# 最小权限 scope 清单（SPEC §4.2，schema/auth 实测 2026-10-12）

单一事实源：`feishu-doc-mcp/src/feishu_doc_mcp/scopes.py` 的 `REQUIRED_SCOPES`。

| # | scope | 覆盖能力 | 复核命令 |
| --- | --- | --- | --- |
| 1 | `docs:document.comment:read` | 读评论列表/线程 | `lark-cli schema drive.file.comments.list` → `_meta.scopes` 最细项 |
| 2 | `docs:document.comment:create` | 回复评论 | `lark-cli schema drive.file.comment.replys.create` |
| 3 | `docs:document.comment:update` | 解决（resolve）评论 | `lark-cli schema drive.file.comments.patch` |
| 4 | `drive:drive.metadata:readonly` | 读文件元信息（owner_id） | `lark-cli schema drive.metas.batch_query` |
| 5 | `docx:document:readonly` | 读文档块 | `lark-cli auth check --scope "docx:document:readonly" --json`（docx 不在 schema 服务列表） |
| 6 | `docx:document` | 块级写文档 | `lark-cli auth check --scope "docx:document" --json` |
| 7 | `board:whiteboard:node:read` | 画板读 | `lark-cli auth scopes --json` 可见性复核 |
| 8 | `board:whiteboard:node:create` | 画板节点创建 | 同上 |
| 9 | `board:whiteboard:node:delete` | 画板节点删除 | 同上 |

注意：

- 该应用**没有** `board:whiteboard:node:update`（`lark-cli auth scopes` 实测）；`whiteboard +update` 经节点增删实现，1–9 即全集。
- 该应用未启用任何文件删除 scope（`drive:drive` 未启用），因此备份为纯本地（SPEC D17），清单中无删除类 scope。
- 若某 scope 有 readonly 变体且只需读，必须用 readonly 变体（第 1、3、4、6 项已遵守）。

## 授权命令（逐域精确，禁止 --recommend / --domain）

```bash
lark-cli auth login \
  --scope "docs:document.comment:read" \
  --scope "docs:document.comment:create" \
  --scope "docs:document.comment:update" \
  --scope "drive:drive.metadata:readonly" \
  --scope "docx:document:readonly" \
  --scope "docx:document" \
  --scope "board:whiteboard:node:read" \
  --scope "board:whiteboard:node:create" \
  --scope "board:whiteboard:node:delete"
```

## 启动自检

```bash
lark-cli auth status --json                                   # identities.user.status == "ready"
lark-cli auth check --scope "<上表 9 项空格分隔>" --json        # missing 必须为 null
```

或直接用 MCP `check_environment`，其 `suggested_login_command` 只含缺失 scope。

## 无超配验收（P4）

`lark-cli auth status --json` 的 user scope 集合与本表的交集 == 本表（用户其他业务授权的 scope 不计）。本系统运行只依赖上表 9 项。
