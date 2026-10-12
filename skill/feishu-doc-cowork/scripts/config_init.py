"""Create ~/.cache/feishu-doc-cowork/config.yaml (SPEC §4.1). Never overwrites.

CLI:  python config_init.py [config_path]
"""

import os
import sys

DEFAULT_PATH = os.path.expanduser("~/.cache/feishu-doc-cowork/config.yaml")

TEMPLATE = """\
runtime:
  poll_interval_sec: 10
  poll_jitter: 0.2
  max_retry_per_comment: 3
  backoff_base_sec: 5                 # 429/5xx 指数退避基数，上限 120s
identity:
  model_name: "GLM5.3"                # 回复格式中的 AI 模型名
  agent_name: "OMP"                   # 回复格式中的 Agent 名
lark_cli:
  binary: "lark-cli"                  # PATH 中的 lark-cli
  identity: "user"                    # 固定 user 身份
"""


def init_config(path=DEFAULT_PATH):
    """Create the config file if absent. Returns (path, created)."""
    if os.path.exists(path):
        return path, False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(TEMPLATE)
    return path, True


def main(argv):
    path = argv[1] if len(argv) > 1 else DEFAULT_PATH
    path, created = init_config(path)
    print(("created: " if created else "exists (untouched): ") + path)


if __name__ == "__main__":
    main(sys.argv)
