"""DocxXML -> markdown + block_map (SPEC §5.3, U2).

Calibrated against live output 2026-10-12: `docs +fetch --doc-format xml
--detail with-ids` returns data.document.content as DocxXML where every
block element carries `id="doxcn..."`; revision lives at
data.document.revision_id. (markdown format silently ignores with-ids —
hence XML.)

The converter is intentionally pragmatic: it renders the block vocabulary
observed in real documents (title/h1-h9/p/ul/ol/li/table/whiteboard/code)
to simple markdown lines, one entry per id-bearing element. Unknown tags
pass through as raw XML lines so nothing is silently dropped.
"""

import re
import xml.etree.ElementTree as ET

from .errors import LarkApiError

_CONTENT_KEYS = ("content", "markdown")
_REVISION_KEYS = ("revision_id", "revision")

_HEADING_TAGS = {f"h{n}": n for n in range(1, 10)}
_INLINE_TAGS = {"b", "i", "u", "s", "span", "cite", "a", "em", "strong"}


def _unwrap_document(data):
    """Accept both flat and document-nested fetch payloads."""
    if isinstance(data, dict) and isinstance(data.get("document"), dict):
        return data["document"]
    return data


def _text(el):
    """Inline text of an element: inline tags stripped, <br/> -> newline."""
    parts = []

    def walk(node):
        if node.text:
            parts.append(node.text)
        for child in node:
            if child.tag == "br":
                parts.append("\n")
            else:
                walk(child)
            if child.tail:
                parts.append(child.tail)

    walk(el)
    return "".join(parts)


def _cell_text(cell):
    """Text of a td/th: join its block children (usually one <p>)."""
    return " ".join(_text(c).strip() for c in cell if _text(c).strip())


def _entry(line, el, block_type=None, parent_id=None, child_index=None,
           extra=None):
    e = {
        "line": line,
        "block_id": el.get("id"),
        "block_type": block_type or el.tag,
        "parent_id": parent_id,
        "child_index": child_index,
    }
    if extra:
        e.update(extra)
    return e


class _Renderer:
    def __init__(self):
        self.lines = []
        self.block_map = []

    def emit(self, text, el=None, **kw):
        self.lines.append(text)
        if el is not None and el.get("id"):
            self.block_map.append(_entry(len(self.lines), el, **kw))

    def render_children(self, parent, parent_id=None, depth=0):
        for index, el in enumerate(parent):
            self.render_block(el, parent_id=parent_id, child_index=index,
                              depth=depth)

    def render_block(self, el, parent_id=None, child_index=None, depth=0):
        tag = el.tag
        eid = el.get("id")
        if tag == "title":
            self.emit(f"# {_text(el).strip()}", el, parent_id=parent_id,
                      child_index=child_index)
        elif tag in _HEADING_TAGS:
            self.emit(f"{'#' * _HEADING_TAGS[tag]} {_text(el).strip()}", el,
                      parent_id=parent_id, child_index=child_index)
        elif tag == "p":
            self.emit(_text(el).strip(), el, parent_id=parent_id,
                      child_index=child_index)
        elif tag in ("ul", "ol"):
            self.render_list(el, parent_id=parent_id, depth=depth)
        elif tag == "table":
            self.render_table(el, parent_id=parent_id, child_index=child_index)
        elif tag == "whiteboard":
            self.emit(f"[whiteboard token={el.get('token', '')}]", el,
                      parent_id=parent_id, child_index=child_index,
                      extra={"whiteboard_token": el.get("token")})
        elif tag in ("code", "pre"):
            body = _text(el).rstrip("\n")
            start_line = len(self.lines) + 1
            self.lines.append("```")
            self.lines.extend(body.splitlines())
            self.lines.append("```")
            if eid:
                self.block_map.append(_entry(
                    start_line, el, block_type="code",
                    parent_id=parent_id, child_index=child_index))
        elif tag == "hr":
            self.emit("---", el, parent_id=parent_id, child_index=child_index)
        else:
            # unknown block (readonly-block, callout, ...): raw passthrough,
            # ids stripped from the markdown line; id-bearing descendants stay
            # addressable via block_map entries pointing at this line.
            raw = ET.tostring(el, encoding="unicode")
            raw = re.sub(r'\sid="[^"]*"', "", raw)
            self.emit(raw, el, parent_id=parent_id, child_index=child_index)
            self._collect_descendant_ids(el, len(self.lines), el.get("id"))

    def _collect_descendant_ids(self, el, line, ancestor_id):
        for child in el.iter():
            if child is el:
                continue
            cid = child.get("id")
            if cid:
                self.block_map.append(_entry(line, child,
                                             parent_id=ancestor_id))

    def render_list(self, list_el, parent_id=None, depth=0):
        marker = "-" if list_el.tag == "ul" else "1."
        for index, li in enumerate(list_el):
            if li.tag != "li":
                self.render_block(li, parent_id=parent_id, depth=depth)
                continue
            # li text up to the first nested list
            text_parts = []
            nested = []
            if li.text:
                text_parts.append(li.text)
            for child in li:
                if child.tag in ("ul", "ol"):
                    nested.append(child)
                else:
                    text_parts.append(_text(child))
                if child.tail:
                    text_parts.append(child.tail)
            indent = "  " * depth
            self.emit(f"{indent}{marker} {''.join(text_parts).strip()}", li,
                      block_type="li", parent_id=parent_id,
                      child_index=index)
            for n in nested:
                self.render_list(n, parent_id=li.get("id") or parent_id,
                                 depth=depth + 1)

    def render_table(self, table_el, parent_id=None, child_index=None):
        table_id = table_el.get("id")
        first_line = len(self.lines) + 1
        flat_index = 0  # documented: flat order over id-bearing cell blocks
        body = [c for c in table_el if c.tag in ("thead", "tbody")] or [table_el]
        row_index = 0
        for section in body:
            for tr in section:
                if tr.tag != "tr":
                    continue
                cells = [c for c in tr if c.tag in ("td", "th")]
                texts = []
                for cell in cells:
                    texts.append(_cell_text(cell))
                self.lines.append("| " + " | ".join(texts) + " |")
                row_line = len(self.lines)
                for col_index, cell in enumerate(cells):
                    for child in cell:
                        if child.get("id"):
                            self.block_map.append(_entry(
                                row_line, child, parent_id=table_id,
                                child_index=flat_index,
                                extra={"row_index": row_index,
                                       "col_index": col_index}))
                            flat_index += 1
                row_index += 1
        if table_id:
            self.block_map.append(_entry(first_line, table_el,
                                         block_type="table",
                                         parent_id=parent_id,
                                         child_index=child_index))


def parse_fetch_output(data):
    """DocxXML fetch payload -> {"markdown", "block_map", "revision_id"}.

    markdown lines carry no ids; block_map entries (1-based line, block_id,
    block_type, parent_id, child_index, optional whiteboard_token) provide
    reversible addressing. Empty content is allowed; non-empty content that
    yields zero id-bearing blocks raises block_map_unresolved (loud failure
    instead of blind editing).
    """
    if not isinstance(data, dict):
        raise ValueError("fetch payload is not an object")
    doc = _unwrap_document(data)
    content = next((doc[k] for k in _CONTENT_KEYS if doc.get(k) is not None), None)
    if content is None:
        raise ValueError(f"fetch payload lacks content keys {_CONTENT_KEYS}")
    revision = next((doc[k] for k in _REVISION_KEYS if doc.get(k) is not None), None)
    if revision is None:
        raise ValueError(f"fetch payload lacks revision keys {_REVISION_KEYS}")

    if not content.strip():
        return {"markdown": "", "block_map": [], "revision_id": revision}

    try:
        root = ET.fromstring(f"<root>{content}</root>")
    except ET.ParseError as e:
        raise LarkApiError(
            code="block_map_unresolved",
            message=f"DocxXML 解析失败：{e}；内容采样：{content.strip()[:200]}",
        ) from e

    renderer = _Renderer()
    renderer.render_children(root)
    if not renderer.block_map:
        raise LarkApiError(
            code="block_map_unresolved",
            message=("文档内容非空但未解析出任何带 id 的块——格式与预期不符。"
                     "内容采样：" + content.strip()[:200]),
        )
    return {
        "markdown": "\n".join(renderer.lines),
        "block_map": renderer.block_map,
        "revision_id": revision,
    }
