"""Feishu document URL parsing (SPEC §5.2, U1)."""

from urllib.parse import urlparse


class LegacyDocError(ValueError):
    """Legacy /doc/ documents have no block-level API; migration required."""

    def __init__(self, token):
        super().__init__(
            f"旧版 doc 文档（token={token}）无块级 API，请先迁移为 docx 后再使用本系统"
        )
        self.token = token


def parse_doc_url(url_or_token):
    """Parse a Feishu doc URL or bare token.

    Returns {"doc_token", "doc_type", "url"} where doc_type is
    "docx" | "wiki". Legacy /doc/ raises LegacyDocError; anything else
    raises ValueError.
    """
    text = url_or_token.strip()
    if not text:
        raise ValueError("empty document URL/token")
    if "/" not in text and "://" not in text:
        return {"doc_token": text, "doc_type": "docx", "url": url_or_token}

    parsed = urlparse(text)
    segments = [s for s in parsed.path.split("/") if s]
    if len(segments) < 2:
        raise ValueError(f"unrecognized document URL: {url_or_token}")
    kind, token = segments[0], segments[1]
    if kind == "docx":
        return {"doc_token": token, "doc_type": "docx", "url": url_or_token}
    if kind == "wiki":
        return {"doc_token": token, "doc_type": "wiki", "url": url_or_token}
    if kind == "doc":
        raise LegacyDocError(token)
    raise ValueError(f"unsupported document type '{kind}' in URL: {url_or_token}")
