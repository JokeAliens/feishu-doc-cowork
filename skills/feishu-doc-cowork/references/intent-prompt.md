# 评论意图判定提示词（SPEC §9）

对每条 owner 评论，基于以下输入做三分类判定：

## 输入要素

- 评论内容（comment.content）
- 被引用原文（comment.quote）
- 完整线程（get_comment_thread 的全部回复，含 owner 追问）
- 文档相关段落（read_document 的 markdown 对应片段）

## 三选一 verdict

| verdict | 定义 | 动作 |
| --- | --- | --- |
| `EDIT_REQUEST` | 明确要求增/删/改文档内容（含表格、画板） | 进入修改流程 |
| `QUESTION_OR_DISCUSS` | 提问、讨论、表态、闲聊 | skipped，不动作、不回复 |
| `OUT_OF_SCOPE` | 是修改要求但超出能力（插入附件、改权限、DSL 无法表达的画板图元等） | skipped，不动作、不回复（v2.0 静默，避免评论噪音） |

## 判定要点

- 祈使句 + 指向文档内容（"把 X 改成 Y"、"删掉这段"、"在第三章加一节"）→ EDIT_REQUEST。
- 疑问句为主（"这里是不是写错了？"、"为什么这么设计？"）→ QUESTION_OR_DISCUSS。即使暗示内容有误，只要没有明确修改指令就不动文档。
- 线程中 owner 的最新表述优先于首条；追问可能把提问升级为修改要求，也可能撤回。
- 拿不准时倾向 QUESTION_OR_DISCUSS——误改文档的代价远高于漏改（漏改可被 owner 追问纠正，误改污染文档与 git 历史）。

## 输出（结构化 JSON，无其他文字）

```json
{
  "verdict": "EDIT_REQUEST | QUESTION_OR_DISCUSS | OUT_OF_SCOPE",
  "reason": "一句话判定依据",
  "edit_intent_summary": "若 EDIT_REQUEST：1-3 句话的修改意图摘要（复用于 commit message 处理摘要）；否则为空字符串"
}
```
