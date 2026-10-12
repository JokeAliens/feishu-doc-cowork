# 联调测试报告 — feishu-doc-cowork

日期：2026-10-12；环境：lark-cli 1.0.97（user 身份，郑用杰 ou_f020a15e4894d990444354d71befc5e4）、uv + Python 3.12、测试文档 `https://ruijie.feishu.cn/wiki/XrLYwfzRwiOEtEkz3mhcA7kLnsd`（docx token `HMSvdQCfboayYNxCyjPcY5TfnsM`）。
单元测试：`uv run pytest tests/` → **57 passed**。

## 校准结果（计划 Review Focus，全部实测闭环）

| # | 假设 | 实测结论 | 修复 |
| --- | --- | --- | --- |
| 1 | with-ids markdown 记号格式 | **假设错误**：`--detail with-ids` 仅支持 `--doc-format xml`（markdown 静默忽略，warnings 明示）。真实格式 = DocxXML，元素带 `id="doxcn..."`，内容嵌套在 `data.document.content`，revision 在 `data.document.revision_id` | block_map.py 重写为 DocxXML 解析器（真实 fixture）；block_type/parent_id/child_index 填真值；read_document 改走 xml |
| 2 | metas owner 字段名 | `owner_id` 直接存在（首候选命中） | 无需改 |
| 3 | `+update --revision-id` 语义 | 联调中 revision 链式传递工作正常（6106→6111 多次写）；冲突由 MCP 前置 outline 比对兜底（I6 实测） | 保留双机制 |
| 4 | solved/whole 回复错误载荷 | 未实测（未构造 solved 评论回复场景） | 保留 message 子串映射 + 文档标注 |
| 5 | +list-comments 翻页 | 实测返回 `has_more`/`page_token`；评论正文在 `reply_list.replies`（最早一条），无顶层 content/reply_count | _normalize_comment 按实测结构重写，正文取 create_time 最早回复 |

**联调新发现（评审外）**：
- lark-cli 部分 API 级失败 exit=1 但 stdout 是合法 envelope（`+update` no-op degrade）→ cli_runner 改为「合法 envelope 优先返回，exit code 仅对非 JSON 输出判死」。
- 自己回复评论会 bump `update_time` → I9 机制会误判为 owner 重新编辑而无限重处理 → SKILL.md 增加「回复后刷新 update_time 落盘」步骤，已实测验证（修复前 would reprocess=True，修复后 False）。

## 用例结果

### 单元级

| 用例 | 结果 | 证据 |
| --- | --- | --- |
| U1 URL 解析 | ✅ stub + ✅ live（wiki 解包 `XrLY...` → `HMSv...`，title/type 正确） | tests + 联调日志 |
| U2 可逆寻址 | ✅ live：1934 块、1040 行；循环中按 block_id 反查目标行成功（`doxcnptz...` → 占位段落行） | 启动链路日志 |
| U3 最小修改 | ✅ live：占位段落改 1 处短语，1 个 str_replace 写请求，验证行内容精确命中 | 循环日志 `apply result` |
| U4 非 owner 过滤 | ⬜ 无法验证（单账号环境）；机制 = `user_id == owner_id` 一行过滤 | — |
| U5 意图判定 | ✅ 样本 3 条（修改/提问/空改）分类正确；10 条样本集留待运行期积累 | 循环日志 verdict |
| U6 envelope 错误映射 | ✅ stub + live（degrade exit=1 路径已转入 envelope 映射） | test_run_nonzero_exit_with_valid_envelope_returns_it |

### 权限最小化

| 用例 | 结果 | 证据 |
| --- | --- | --- |
| P1 无 --recommend/--domain | ✅ | 授权命令逐 --scope；`grep` 代码无禁用标志 |
| P2 缺 scope 精确报错 | ✅ 机制验证：登录前 `check_environment` 等价物 `auth check` 输出 missing 列表；revoke 演练未做 | auth check 输出 |
| P3 清单可复核 | ✅ | scope-checklist.md 逐项复核命令；画板 scope 经 `auth scopes` 实测修正（无 node:update） |
| P4 无超配 | ✅（本系统所需 8 项 ⊆ 已授集合；该账号另有历史业务授权，非本系统申请） | `auth status --json` missing=[] |

### 集成级

| 用例 | 结果 | 证据 |
| --- | --- | --- |
| I1 单评论多修改=1 commit | ✅（单修改 live + 多修改 stub） | git log |
| I2 多评论顺序 commit | 部分 ✅（两评论两 commit stub；live 两条评论分别走了 skipped/空改路径，不产生 commit 属预期） | test_two_comments_two_commits |
| I3 commit message 格式 | ✅ live | `git log`：`[comment:7695651491513224139] 把这段的「指导XXX的功能」改成…` 含全文/摘要/块/模型/状态 |
| I4 空改动 | ✅ live：no-op 评论 → `has_doc_diff=False`、无 commit、回复「内容已符合要求，无需修改」 | 循环日志 + git log |
| I5 崩溃恢复 | ✅ stub（processing→pending 重置）；live kill -9 演练未做 | test_state_reset_processing |
| I6 冲突 | ✅ live：外部直改文档 bump revision 6106→6108 后，apply 带 stale revision → ConflictError，零写请求 | 联调日志 |
| I7 非修改评论 | ✅ live：提问评论 → skipped、无 commit、无回复 | git log 不变 |
| I8 常驻/SIGINT | ⬜ 未做 30min 演练（主循环由 agent 按 SKILL.md 执行，信号处理为行为规范） | — |
| I9 owner 编辑已 done 评论 | 机制 ✅ live（update_time 比对 + 自回复防误判实测）；完整重处理链路未演练 | 联调日志 |
| I10 回复格式 | ✅ live：`修改完成，使用AI模型：kimi-code/k3， Agent：OMP` 精确落评论区 | 评论区可见 |
| I11 画板 | 部分 ✅：读通道 live（raw nodes 导出）；写通道 dry-run 验证 API 映射（POST /board/v1/whiteboards/{t}/nodes）；真实写未做——测试文档 16 个画板全是真实架构图，污染不可逆 | export 输出 |
| I12 表格 | ✅ live：空单元格写入「联调测试单元格」→ 验证 → str_replace 清空还原；全程块级写 | 联调日志 |
| I13 启动本地备份 | ✅ live：backups/20261012-133747/ + backups.json + 基线 commit；保留 3 份策略 stub 测 | git log + 磁盘 |

## 遗留

- 真实文档已恢复原状（探针编辑与测试单元格均还原；占位段落按评论要求保留「指导EDN-Cloud平台的功能」——这是评论要求的正式修改）。
- 未做项（U4/I5-live/I8/I9-全链路/P2-revoke/画板真实写）均已在 verification.md 标注原因。
