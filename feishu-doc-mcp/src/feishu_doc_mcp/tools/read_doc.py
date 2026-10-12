"""read_document tool (SPEC §5.3)."""

from ..block_map import parse_fetch_output
from ..cli_runner import run_lark_cli, unwrap


def read_document(doc_id):
    """Fetch the full document as markdown plus a reversible block map."""
    data = unwrap(run_lark_cli([
        "docs", "+fetch",
        "--doc", doc_id,
        "--doc-format", "markdown",
        "--detail", "with-ids",
        "--scope", "full",
    ]))
    return parse_fetch_output(data)
