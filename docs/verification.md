# 验收清单（SPEC §11）

准备：测试文档（含段落、表格、画板）+ 已按 `skill/feishu-doc-cowork/references/scope-checklist.md` 精确授权的 lark-cli（user 身份）。

标记：✅ 已通过（附证据）/ ❌ 未通过 / ⬜ 未执行。`[stub]` = 已由单元测试覆盖（stub lark-cli）；`[live]` = 需真实授权联调。

## 11.1 单元级

| 用例 | 状态 | 证据 |
| --- | --- | --- |
| U1 URL 解析：docx URL/裸 token/wiki/旧 doc 报错 | ✅ [stub] | `tests/test_url_parse.py` 5 例；wiki 解包 `tests/test_doc_info.py::test_wiki_url_unwrapped_via_inspect` |
| U2 read_document 可逆寻址 | 部分 ✅ [stub] ✅ [stub+live] | 已联调校准：with-ids 仅支持 xml → DocxXML 解析器（真实 fixture）；block_type/parent_id/child_index 填真值；详见 docs/test-report.md |
| U3 最小修改（1 句 → 1 个写请求，无全量写） | ✅ [stub] | `tests/test_block_ops.py::test_update_text_single_write_no_overwrite` |
| U4 非 owner 评论不进入处理 | ⬜ 单账号环境无法验证；机制为 `user_id == owner_id` 过滤 |
| U5 意图判定准确率（5 修改/3 提问/2 超范围） | 部分 ✅（3 条样本 live 分类正确）| docs/test-report.md U5 |
| U6 envelope 错误映射 + hint 透传 | ✅ [stub] | `tests/test_cli_runner.py::test_unwrap_error_raises_with_hint`、`tests/test_server.py::test_lark_error_serialized_with_hint` |

## 11.2 权限最小化

| 用例 | 状态 | 证据 |
| --- | --- | --- |
| P1 全程未用 --recommend/--domain | ✅（代码+文档静态保证） | `grep -r "recommend\|--domain" skill/ core/src` 仅出现在禁止性说明中 |
| P2 revoke 一个 scope → 报精确补授权命令 | 部分 ✅（missing 检测机制 live 验证；revoke 演练未做）| test-report P2 |
| P3 README 清单可 schema 复核 | ✅ | scope-checklist.md 每项带复核命令；1–3 项已 schema 实测，4–8 项 auth check/scopes 实测 |
| P4 auth status 已授集合 ⊇ 清单且无超配 | ✅ | `auth status --json` missing=[]，test-report P4 |

## 11.3 集成级（git 铁律）

| 用例 | 状态 | 证据 |
| --- | --- | --- |
| I1 单评论多修改 = 1 commit | ✅ [stub+live 单评论单 commit] | test_two_comments_two_commits + git log |
| I2 多评论顺序 commit 互不包含 | ✅ [live] | docs/test-report.md I1/I2 |
| I3 commit message 格式 | ✅ [stub] | `test_commit_comment_message_format`、`test_commit_comment_truncates_first_line_at_50` |
| I4 空改动不 commit | ✅ [stub+live] | `test_has_doc_diff` + 联调 no-op 评论无 commit 有回复 |
| I5 崩溃恢复（kill -9 → 无重复 commit/回复） | ✅ [stub]（live kill 演练未做）| `test_state_reset_processing` |
| I6 冲突 CONFLICT 重试 | ✅ [stub+live] | `test_conflict_raises_before_any_write` + 联调 I6（6106→6108 CONFLICT 零写请求） |
| I7 非修改评论无 commit 无回复 | ✅ [live] | test-report I7 |
| I8 常驻 30min + SIGINT 优雅退出打印统计 | ⬜ 未做 30min 演练 | test-report I8 |
| I9 owner 编辑已 done 评论 → 重新处理新 commit | ✅ 机制 live（update_time 比对+自回复防误判）| test-report I9 |
| I10 回复格式逐字匹配 | ✅ [stub] | `test_reply_comment_content_json`（含中文标点与空格） |
| I11 画板修改 | 部分 ✅ [stub+live 读/dry-run 写] | 真实写因污染风险未做，test-report I11 |
| I12 表格增行/改单元格 | ✅ [stub+live 单元格写+还原] | test-report I12 |
| I13 启动本地备份：backups/{ts}/ + backups.json + 1 commit，只留 3 份 | ✅ [stub+live] | backups/ + backups.json + 基线 commit，test-report I13 |

## 联调阻塞项

`lark-cli auth status` 实测：user identity `missing (refresh token expired)`。联调前必须：

```bash
lark-cli auth login --scope "docs:document.comment:read" --scope "docs:document.comment:create" --scope "drive:drive.metadata:readonly" --scope "docx:document:readonly" --scope "docx:document" --scope "board:whiteboard:node:read" --scope "board:whiteboard:node:create" --scope "board:whiteboard:node:delete"
```

联调第一步校准（计划 Review Focus）：
1. 真实 `+fetch --detail with-ids` 输出 → 校准 `cowork_core/block_map.py: BLOCK_ID_PATTERNS` 与测试 fixture；
2. 真实 metas batch_query 响应 → 校准 `doc_info.py: _OWNER_KEYS`；
3. 真实 `+update --revision-id` 冲突语义 → 决定是否保留 cowork 侧独立 revision 比对（已保留，联调验证）（当前默认保留）。
