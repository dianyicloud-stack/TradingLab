from app.shell.registry import Module, Page
from contracts.system import HealthCheck
from pathlib import Path
from html import escape

def create_module(system_health):
    def health():return HealthCheck('system','System',system_health.read()['overall'],'最近完成的诊断；不代表全部业务已验收')
    def page():
        rows=''.join('<tr>'+''.join('<td>'+escape(str(v if v is not None else '尚未检查'))+'</td>' for v in (r['name'],r['status'],r['detail'],r.get('checked_at')))+'</tr>' for r in system_health.read()['checks'])
        return Page('后台持续工作；页面读取最近完成的状态，深度检查由你主动运行。',(),content_html=f'''
<section class="panel" id="runtime-center"><h2>运行中心</h2><p id="runtime-intent">正在读取后台运行状态…</p>
<div class="toolbar"><button data-runtime-action="start" data-target="background">启动后台</button><button data-runtime-action="stop" data-target="background">停止后台</button><button data-runtime-action="restart" data-target="web">重启网页服务</button><button data-runtime-action="restart" data-target="agent">重启行情采集</button></div>
<p id="runtime-operation" role="status"></p><table><thead><tr><th>服务</th><th>希望状态</th><th>当前状态</th><th>进程</th><th>最近检查</th><th>说明</th></tr></thead><tbody id="runtime-services"></tbody></table>
<details><summary>异常处理与本机控制</summary><p>正常操作先等待已有任务安全收尾。强制操作仅用于异常服务；不能撤回已经发出的请求。</p>
<button data-runtime-action="force-stop" data-target="web">强制停止网页服务</button><button data-runtime-action="force-restart" data-target="web">强制重启网页服务</button>
<button data-runtime-action="force-stop" data-target="agent">强制停止行情采集</button><button data-runtime-action="force-restart" data-target="agent">强制重启行情采集</button><p>本机入口：项目 tools / background_status.cmd；网页不可用时仍可控制。</p></details></section>
<section class="panel"><h2><a href="/system/market-source">数据源</a></h2><p>唯一正式行情源 Market Data Agent 的连接与采集状态。</p></section>
<section class="panel" id="ai-model-settings"><h2>AI模型</h2>
<p id="ai-current">正在读取当前默认配置…</p><form id="ai-model-form" class="toolbar">
<label>服务商 <select id="ai-provider"></select></label><label>模型 <select id="ai-model"></select></label>
<label>推理强度 <select id="ai-effort"></select></label><button type="submit">保存默认配置</button>
<button type="button" id="ai-verify">验证连接与输出</button></form><p>保存只影响新登记任务；验证最多一次生成请求，可能产生少量 API 费用，不交易、不发通知。</p>
<p id="ai-connection"></p><p id="ai-result" role="status"></p>
<details><summary>其他模型与输出设置</summary><p>远程模型可访问不代表已通过分析能力审核。未知模型只保存草稿。</p>
<label>实际模型 ID <input id="ai-manual-model" maxlength="100"></label><button id="ai-draft">保存草稿</button>
<button id="ai-refresh-models">刷新远程模型目录</button><p id="ai-model-directory"></p>
<label>输出上限（留空沿用服务商设置） <input id="ai-output" type="number" min="1"></label>
<p id="ai-config-source"></p></details></section>
<section class="panel"><h2>Telegram 分析结果通知</h2><p id="telegram-status">正在读取通知状态…</p></section>
<section class="panel"><h2>数据维护</h2><p id="maintenance-summary">等待后台测量；当前数字尚不可用。</p><p>日内明细保留最近一个准备完成的交易日；账户、手工保存和计算基准受保护。</p><button id="maintenance-preview">预览清理</button> <button id="maintenance-apply">按策略清理</button><p id="maintenance-result"></p></section>
<section class="panel"><h2>系统检查</h2><p id="system-status">正在读取最近检查结果…</p><button id="system-diagnose">运行诊断</button>
<p>完整冻结文件 Hash、存储和组件检查在后台执行。检查时间不会随页面刷新改变。</p>
<table><thead><tr><th>组件</th><th>状态</th><th>说明</th><th>检查时间</th></tr></thead><tbody id="system-checks">{rows}</tbody></table></section>
<details class="panel"><summary>高级审计</summary><p>原始 AI 意见、输入与账户执行记录仍由所属模块保存。</p><a href="/account">账户执行记录</a><p><label>股票代码 <input id="audit-symbol" placeholder="例如 bj920161"></label><button id="audit-load">读取原始AI意见与执行状态</button></p><pre id="audit-result" style="white-space:pre-wrap;overflow-wrap:anywhere"></pre></details>
''',scripts=('/assets/system-status.js','/assets/ai-settings.js','/assets/runtime-center.js'))
    return Module('system','System','/system','系统状态',health,page)

class HealthRouter:
    def __init__(self,health):self.health=health
    def accepts_post(self,path):return path=='/api/system/diagnostics'
    def route(self,method,path,payload=None):
        if method=='GET' and path=='/assets/system-status.js':return 200,Path(__file__).with_name('static').joinpath('system-status.js').read_bytes(),'text/javascript; charset=utf-8'
        if method=='GET' and path=='/api/system/summary':return 200,self.health.read(),None
        if method=='POST' and path=='/api/system/diagnostics':return 202,self.health.diagnose(),None
        return None
