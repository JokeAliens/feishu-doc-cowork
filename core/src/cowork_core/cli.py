"""cowork CLI — the agent-facing entrypoint (replaces the removed MCP layer).

Every subcommand prints one JSON object to stdout: the tool result on
success (exit 0), or {"error": {code, message, lark_code, hint}} on
failure (exit 1). All lark-cli access goes through the tool functions.

Subcommands mirror the former MCP tools one-to-one.
"""

import argparse
import json
import sys

from .errors import CliExecError, LarkApiError
from .tools.block_ops import apply_block_operations
from .tools.comments import (
    get_comment_thread, list_comments, reply_comment, resolve_comment,
)
from .tools.doc_info import get_doc_info
from .tools.environment import check_environment
from .tools.read_doc import read_document


def _read_ops(spec):
    """--ops value: inline JSON, @file, or '-' for stdin."""
    if spec == "-":
        return json.load(sys.stdin)
    if spec.startswith("@"):
        with open(spec[1:], encoding="utf-8") as f:
            return json.load(f)
    return json.loads(spec)


def _build_parser():
    p = argparse.ArgumentParser(prog="cowork",
                                description="Feishu docx cowork CLI over lark-cli")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check-environment")

    p_info = sub.add_parser("get-doc-info")
    p_info.add_argument("doc_url")

    p_read = sub.add_parser("read-document")
    p_read.add_argument("doc_id")

    p_list = sub.add_parser("list-comments")
    p_list.add_argument("doc_id")
    p_list.add_argument("--solved", action="store_true")

    p_thread = sub.add_parser("get-comment-thread")
    p_thread.add_argument("doc_id")
    p_thread.add_argument("comment_id")

    p_ops = sub.add_parser("apply-ops")
    p_ops.add_argument("doc_id")
    p_ops.add_argument("--ops", required=True,
                       help="JSON array, @file, or - for stdin")
    p_ops.add_argument("--expected-revision", type=int, required=True)

    p_reply = sub.add_parser("reply")
    p_reply.add_argument("doc_id")
    p_reply.add_argument("comment_id")
    p_reply.add_argument("content")

    p_resolve = sub.add_parser("resolve")
    p_resolve.add_argument("doc_id")
    p_resolve.add_argument("comment_id")
    return p


def _dispatch(args):
    if args.cmd == "check-environment":
        return check_environment()
    if args.cmd == "get-doc-info":
        return get_doc_info(args.doc_url)
    if args.cmd == "read-document":
        return read_document(args.doc_id)
    if args.cmd == "list-comments":
        return list_comments(args.doc_id, is_solved=args.solved)
    if args.cmd == "get-comment-thread":
        return get_comment_thread(args.doc_id, args.comment_id)
    if args.cmd == "apply-ops":
        return apply_block_operations(args.doc_id, _read_ops(args.ops),
                                      args.expected_revision)
    if args.cmd == "reply":
        return reply_comment(args.doc_id, args.comment_id, args.content)
    if args.cmd == "resolve":
        return resolve_comment(args.doc_id, args.comment_id)
    raise ValueError(args.cmd)


def main(argv=None):
    args = _build_parser().parse_args(argv)
    try:
        result = _dispatch(args)
    except LarkApiError as e:
        print(json.dumps(e.to_dict(), ensure_ascii=False))
        return 1
    except (CliExecError, ValueError) as e:
        code = "invalid_params" if isinstance(e, ValueError) else "cli_exec"
        print(json.dumps({"error": {"code": code, "message": str(e),
                                    "lark_code": None, "hint": None}},
                         ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
