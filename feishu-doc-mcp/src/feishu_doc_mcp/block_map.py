"""block_map construction from `docs +fetch --detail with-ids` output (SPEC §5.3, U2).

BLOCK_ID_PATTERNS is the single parsing point. The real with-ids marker
format has not been calibrated against a live fetch yet (Review Focus #1);
when it is, adjust these patterns and the test fixture only.
"""

import re

BLOCK_ID_PATTERNS = [
    # trailing HTML-comment marker:  some text <!-- block_id: blk001 -->
    re.compile(r"\s*<!--\s*block_id:\s*(?P<id>[A-Za-z0-9_-]+)\s*-->\s*$"),
    # line-prefix marker:  blk008 some text
    re.compile(r"^(?P<id>blk[A-Za-z0-9_-]+)\s+"),
]

_CONTENT_KEYS = ("content", "markdown")
_REVISION_KEYS = ("revision_id", "revision")


def _extract(pattern, line):
    m = pattern.search(line)
    return m.group("id") if m else None


def parse_fetch_output(data):
    """Turn a +fetch envelope-data dict into markdown + block_map + revision_id.

    Returns {"markdown": str, "block_map": [BlockEntry], "revision_id": int}.
    BlockEntry: {"line", "block_id", "block_type", "parent_id", "child_index"}.
    Markers are stripped from the returned markdown; block_map line numbers
    refer to the stripped markdown (1-based).
    """
    if not isinstance(data, dict):
        raise ValueError("fetch payload is not an object")
    content = next((data[k] for k in _CONTENT_KEYS if data.get(k)), None)
    if content is None:
        raise ValueError(f"fetch payload lacks content keys {_CONTENT_KEYS}")
    revision = next((data[k] for k in _REVISION_KEYS if data.get(k) is not None), None)

    clean_lines = []
    block_map = []
    for raw_line in content.splitlines():
        block_id = None
        line = raw_line
        for pattern in BLOCK_ID_PATTERNS:
            block_id = _extract(pattern, line)
            if block_id:
                line = pattern.sub("", line).rstrip() if pattern is BLOCK_ID_PATTERNS[0] \
                    else line[pattern.search(line).end():]
                break
        clean_lines.append(line)
        if block_id:
            block_map.append({
                "line": len(clean_lines),
                "block_id": block_id,
                "block_type": None,
                "parent_id": None,
                "child_index": None,
            })
    return {
        "markdown": "\n".join(clean_lines),
        "block_map": block_map,
        "revision_id": revision,
    }
