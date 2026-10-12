"""Subprocess execution of lark-cli with envelope parsing.

Contract (D16): every call carries `--format json`; success is judged by
`ok == true` in the envelope plus exit code 0, never by an inner `code == 0`.
"""

import json
import os
import shlex
import subprocess

from .errors import CliExecError, LarkApiError

DEFAULT_TIMEOUT = 60.0


def _bin_argv():
    """lark-cli executable argv, overridable for tests.

    LARK_CLI_BIN: binary path (default "lark-cli").
    LARK_CLI_BIN_ARGS: optional extra argv (shlex-split) appended after the
    binary, e.g. a script path when LARK_CLI_BIN is an interpreter.
    """
    binary = os.environ.get("LARK_CLI_BIN", "lark-cli")
    extra = shlex.split(os.environ.get("LARK_CLI_BIN_ARGS", ""))
    return [binary, *extra]


def run_lark_cli(args, *, dry_run=False, timeout=DEFAULT_TIMEOUT):
    """Run `lark-cli <args> --format json` and return the parsed envelope.

    Raises CliExecError on execution-level failure (missing binary, timeout,
    non-zero exit, non-JSON output). API-level failure (ok == false with
    exit 0) is returned as an envelope for the caller to unwrap.
    """
    argv = [*_bin_argv(), *args]
    if dry_run:
        argv.append("--dry-run")
    argv.extend(["--format", "json"])
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError as e:
        raise CliExecError(f"lark-cli binary not found: {argv[0]}") from e
    except subprocess.TimeoutExpired as e:
        raise CliExecError(f"lark-cli timed out after {timeout}s: {args}") from e
    if proc.returncode != 0:
        # lark-cli exits non-zero for some API-level failures while still
        # emitting a valid envelope (observed 2026-10-12: +update degrade
        # exit 1 with ok:false + warnings). Prefer the envelope so callers
        # get code/hint via unwrap; only non-JSON output is an exec error.
        try:
            envelope = json.loads(proc.stdout)
            if isinstance(envelope, dict) and "ok" in envelope:
                return envelope
        except json.JSONDecodeError:
            pass
        raise CliExecError(
            f"lark-cli exited {proc.returncode}: {args}\n"
            f"stdout: {proc.stdout.strip()}\nstderr: {proc.stderr.strip()}"
        )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise CliExecError(
            f"lark-cli emitted non-JSON output: {proc.stdout[:500]}"
        ) from e


def unwrap(envelope):
    """Return envelope data on success; raise LarkApiError otherwise."""
    if envelope.get("ok") is True:
        return envelope.get("data")
    error = envelope.get("error") or {}
    code = error.get("subtype") or error.get("type") or "unknown"
    raise LarkApiError(
        code=code,
        message=error.get("message", "unknown lark-cli error"),
        hint=error.get("hint"),
        lark_code=error.get("code"),
    )
