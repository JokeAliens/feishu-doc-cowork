"""Fake lark-cli binary for tests.

Behaviour is driven entirely by env vars:
- FAKE_LARK_RESPONSES: path to a JSON file with a list of rules:
    {"argv_contains": ["auth", "status"], "stdout": {...}, "exit": 0}
  First rule whose tokens all appear in argv (in order) wins.
  stdout is JSON-dumped if it is not a string.
- FAKE_LARK_LOG: path to a JSONL file; every invocation appends {"argv": [...]}.

No matching rule -> prints an error envelope and exits 2.
"""

import json
import os
import sys


def _matches(rule_argv, argv):
    it = iter(argv)
    return all(token in it for token in rule_argv)


def main():
    argv = sys.argv[1:]
    log_path = os.environ.get("FAKE_LARK_LOG")
    if log_path:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"argv": argv}, ensure_ascii=False) + "\n")

    rules_path = os.environ.get("FAKE_LARK_RESPONSES")
    rules = []
    if rules_path and os.path.exists(rules_path):
        with open(rules_path, encoding="utf-8") as f:
            rules = json.load(f)

    for rule in rules:
        if _matches(rule.get("argv_contains", []), argv):
            out = rule.get("stdout", "")
            if not isinstance(out, str):
                out = json.dumps(out, ensure_ascii=False)
            sys.stdout.write(out)
            if not out.endswith("\n"):
                sys.stdout.write("\n")
            sys.exit(rule.get("exit", 0))

    sys.stdout.write(json.dumps({
        "ok": False,
        "error": {
            "type": "validation",
            "subtype": "no_stub_rule",
            "message": f"fake lark-cli: no rule matched argv {argv}",
            "hint": None,
        },
    }, ensure_ascii=False) + "\n")
    sys.exit(2)


if __name__ == "__main__":
    main()
