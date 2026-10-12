"""Error types for feishu-doc-mcp."""


class CliExecError(Exception):
    """lark-cli binary missing, timed out, exited non-zero, or emitted non-JSON."""


class LarkApiError(Exception):
    """lark-cli returned an envelope with ok == false."""

    def __init__(self, code, message, hint=None, lark_code=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.lark_code = lark_code

    def to_dict(self):
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "lark_code": self.lark_code,
                "hint": self.hint,
            }
        }
