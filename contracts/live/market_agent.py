"""MarketAgent 1.0: source owner commands and read-only aggregate DTOs."""
from typing import Protocol

VERSION='1.0'
COMMANDS={'ADD','PAUSE','RESUME','STOP','PARAMETERS','BOARD','IMMEDIATE','RESERVE_SESSIONS','DELETE_PLAN','DELETE'}

class MarketAgentPort(Protocol):
    def query(self) -> dict: ...
    def command(self, payload:dict) -> dict: ...
    def metadata(self, payload:dict) -> dict: ...

class AgentError(ValueError):
    def __init__(self,code,message=None,status=409):
        super().__init__(message or code);self.code=code;self.status=status
