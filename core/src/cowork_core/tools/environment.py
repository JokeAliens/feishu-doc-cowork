"""check_environment tool (SPEC §5.1, §4.3)."""

from ..cli_runner import run_lark_cli
from ..errors import CliExecError
from ..scopes import REQUIRED_SCOPES


def _login_command(scopes):
    parts = " ".join(f'--scope "{s}"' for s in scopes)
    return f"lark-cli auth login {parts}" if parts else ""


def check_environment():
    """Check lark-cli login state and minimal-scope coverage.

    Returns {"logged_in": bool, "missing_scopes": [...],
             "suggested_login_command": str}.
    """
    try:
        status_env = run_lark_cli(["auth", "status"])
    except CliExecError as e:
        return {
            "logged_in": False,
            "missing_scopes": list(REQUIRED_SCOPES),
            "suggested_login_command": (
                f"lark-cli unavailable: {e}. Install @larksuite/cli first, then: "
                + _login_command(REQUIRED_SCOPES)
            ),
        }

    identities = (status_env.get("data") or status_env).get("identities") or {}
    user = identities.get("user") or {}
    logged_in = user.get("status") == "ready"

    if not logged_in:
        return {
            "logged_in": False,
            "missing_scopes": list(REQUIRED_SCOPES),
            "suggested_login_command": _login_command(REQUIRED_SCOPES),
        }

    # One call checks all scopes; envelope shape (grounded 2026-10-12):
    # {"ok": true, "granted": [...], "missing": null|[...]}
    check_env = run_lark_cli([
        "auth", "check", "--scope", " ".join(REQUIRED_SCOPES),
    ])
    payload = check_env.get("data") or check_env
    missing = payload.get("missing") or []
    return {
        "logged_in": True,
        "missing_scopes": list(missing),
        "suggested_login_command": _login_command(missing),
    }
