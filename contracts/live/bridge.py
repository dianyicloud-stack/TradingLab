"""Value-only errors shared by Live and its current source/AI adapters."""


class BridgeError(ValueError):
    def __init__(self, code, message='实时桥接操作未完成。', status=409):
        super().__init__(message)
        self.code, self.http_status = code, status
