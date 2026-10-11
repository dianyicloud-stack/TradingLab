"""Trading Lab Account Contract 2.0; contains no filesystem capabilities."""
from typing import Protocol

ACCOUNT_TYPES = ('LIVE_SHADOW', 'REPLAY_SANDBOX', 'SIMULATION_SANDBOX')
SOURCES = ('LIVE_AI_AUTO', 'LIVE_AI_CONFIRMED', 'LIVE_MANUAL', 'LEARNING', 'REPLAY', 'SIMULATION')
OWNERS = ('AI_MANAGED', 'MANUAL_PROTECTED', 'LEARNING', 'REPLAY', 'SIMULATION', 'LEGACY_UNKNOWN')
ACTIONS = ('NONE', 'OPEN', 'ADD', 'REDUCE', 'EXIT', 'HOLD')
EXECUTION_STATES = ('CREATED','POLICY_REJECTED','READY','DEFERRED','PARTIALLY_EXECUTED','EXECUTED','VOIDED','INVALID_AFTER_REBUILD','FAILED')


class AccountError(ValueError):
    def __init__(self, code, message=None, status=409):
        self.code, self.http_status = code, status
        super().__init__(message or code)


class PortfolioPort(Protocol):
    def context(self, account_id: str, symbol: str) -> dict: ...
    def submit(self, account_id: str, intent: dict) -> dict: ...
    def state(self, account_id: str) -> dict: ...


class QuotePort(Protocol):
    def quote(self, account: dict, symbol: str, visible_through: str) -> dict: ...


class AdvisoryPortfolioPort(Protocol):
    def context(self, symbol: str, account_type: str='LIVE_SHADOW', context_id: str|None=None) -> dict: ...
    def on_advisory(self, opinion: dict, frozen: dict, confirmed: bool=False) -> dict: ...

# Explicitly preserves existing realtime manual eligibility. History never enters
# this port; Telegram eligibility does not grant execution authorization.
LIVE_EXECUTION_TRIGGERS=('AUTO_EVENT','MANUAL','MANUAL_REANALYSIS')
