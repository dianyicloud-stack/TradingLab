from app.shell.registry import Module, Page
from app.live.view import page
from contracts.system import HealthCheck


def create_module(health):
    # Detailed source health comes from the independent Live read model. The
    # HTML shell must not synchronously fetch the Agent's full state.
    return Module("live", "Live", "/live", "实时市场",
                  lambda:HealthCheck('live_page','Live','UNKNOWN','来源状态由后台读模型显示'),page)
