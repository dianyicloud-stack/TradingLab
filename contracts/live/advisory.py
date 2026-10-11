"""Stable value-only contracts for M2.2 Fast Advisory."""
from typing import Protocol
from contracts.live.bridge import BridgeError

class AdvisoryProviderFailure(BridgeError):
    """Allowlisted transport diagnostics; keep the existing HTTP error code."""
    def __init__(self,metadata):
        super().__init__('ADVISORY_PROVIDER_ERROR','AI服务调用未完成；最近成功意见保留，请查看失败原因。',502)
        self.failure_metadata=metadata

REASONING=('none','low','medium','high','xhigh','max')
TRIGGERS=('AUTO_EVENT','MANUAL','MANUAL_REANALYSIS')
AUTO_AI_MODES=('OFF','IMPORTANT_ONLY','ALL_EVENTS')
FRESHNESS_STATES=('FRESH','DELAYED','STALE','UNKNOWN')
CHANGE_SEVERITIES=('INFO','NOTICE','IMPORTANT','CRITICAL')

# Product semantics shared by Advisory DTOs and presentation.  Frozen Formal
# Decision values are translated at the boundary; their protocol is unchanged.
ACTIONS={
    'WATCH':{'machine_code':'WATCH','zh':'观察','description':'不新增风险暴露，等待下一条件确认'},
    'WAIT':{'machine_code':'WAIT','zh':'等待','description':'当前证据不足，等待有效增量'},
    'HOLD':{'machine_code':'HOLD','zh':'维持','description':'维持当前风险暴露并继续验证假设'},
    'ADD':{'machine_code':'ADD','zh':'增加','description':'建议增加风险暴露，仍需用户主动执行'},
    'REDUCE':{'machine_code':'REDUCE','zh':'降低','description':'建议降低风险暴露，仍需用户主动执行'},
    'EXIT':{'machine_code':'EXIT','zh':'退出','description':'退出当前假设或风险暴露，仍需用户主动执行'},
}
ACTION_ALIASES={'NO_ACTION':'WATCH'}

def action_definition(value:str) -> dict:
    code=ACTION_ALIASES.get(value,value)
    return ACTIONS.get(code,{'machine_code':code,'zh':code,'description':'沿用冻结正式协议语义'})

class AdvisoryAIProvider(Protocol):
    def catalog(self) -> dict: ...
    def analyze(self, frozen_input:dict, provider:str, model:str, reasoning:str, prompt:str, schema:dict) -> dict: ...

class AdvisoryRuntimeRepository(Protocol):
    def settings(self) -> dict: ...
    def save_setting(self, scope:str, value:dict, stamp:str) -> None: ...
    def cursor(self, tracking_session_id:str) -> dict|None: ...
    def save_cursor(self, value:dict) -> None: ...
    def commit_success(self, frozen_input:dict, opinion:dict) -> None: ...

class AdvisoryOpinionRepository(Protocol):
    def append(self, frozen_input:dict, opinion:dict) -> None: ...
    def latest(self, symbol:str, identity:str|None=None) -> dict|None: ...
    def history(self, symbol:str, limit:int=50, identity:str|None=None) -> list[dict]: ...
