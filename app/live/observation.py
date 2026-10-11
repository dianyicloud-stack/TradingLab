"""Data Observation UI/API, exclusively through the market-owner Contract."""
from pathlib import Path
from app.shell.registry import Module,Page
from contracts.system import HealthCheck
from contracts.live.market_agent import AgentError
import hashlib,json

HTML='''<section id="data-observation"><p id="data-status" role="status">正在读取后台数据服务…</p>
<p>跟踪设置由后台保存。关闭此页面不停止采集；删除跟踪不清仓；已被业务引用的历史独立保留。</p>
<details id="history-panel" class="history-panel"><summary>日 / 周 / 月 K线与历史收盘分析</summary>
<p>图表按需加载；实时五分钟观察继续在下方运行。历史分析不影响账户、通知或自动分析。</p>
<div class="history-controls"><label>模式<select id="history-mode"><option value="LIVE">实时</option><option value="HISTORY_EOD">历史日期</option></select></label>
<label>股票<input id="history-symbol" placeholder="bj920161" pattern="(sh|sz|bj)[0-9]{6}"></label>
<label>截止交易日<input id="history-date" type="date"></label>
<label>K线<select id="history-period"><option value="DAY">日</option><option value="WEEK">周</option><option value="MONTH">月</option></select></label>
<label>量能周期<select id="history-volume"><option value="DAY">日</option><option value="WEEK">周</option><option value="MONTH">月</option></select></label>
<label>样本<select id="history-samples"><option>10</option><option selected>20</option><option>30</option><option>60</option></select></label>
<label>本次服务商 <select id="history-provider"></select></label><label>本次模型 <select id="history-model"></select></label><label>推理强度 <select id="history-effort"></select></label><span id="history-model-message"></span><button id="history-load" type="button">加载 K线</button><button id="history-more" type="button">向前加载更多</button><button id="history-analyze" type="button" disabled>基于此历史数据分析</button></div>
<p id="history-status" role="status">展开后选择股票加载；不复权，成交量单位为股，1W股＝10000股。</p>
<div id="history-existing" hidden><span>今日已有相同历史分析结果</span> <a id="history-existing-link">查看已有结果</a> <button id="history-reanalyze" type="button">重新分析</button></div>
<div id="history-chart"></div><p id="history-crosshair"></p><p id="history-volume-summary"></p>
<details id="history-bar-inspect"><summary>查看本根数据（诊断原文）</summary><pre id="history-bar-data"></pre></details>
<p class="history-attribution">TradingView Lightweight Charts™ · Copyright © 2025 TradingView, Inc. <a href="https://www.tradingview.com/" target="_blank" rel="noopener">TradingView</a> · <a href="/assets/charts-notice">声明</a> · <a href="/assets/charts-license">Apache 2.0</a></p></details>
<details><summary>跟踪设置</summary><form id="tracking-form">
<label>股票代码<input name="symbol" required pattern="(sh|sz|bj)?[0-9]{6}"></label>
<button type="button" id="lookup-stock">查询名称与板块</button><label>可选板块<select id="lookup-board"><option value="">查询后选择</option></select></label>
<label>股票名称<input name="name" required></label><label>板块代码<input name="board_code" required></label>
<label>板块名称<input name="board_name" required></label><button>添加并跟踪</button><button type="button" id="update-board">更新该股票板块</button></form>
<label>同时段量比样本<select id="volume-days"><option value="20">20个交易日</option><option value="10">10个交易日</option></select></label><button id="save-parameters">保存观察参数</button>
<p>暂停重点观察仍继续采集，保留原版含义。删除会清理跟踪工作数据并保留受保护历史，持仓报价仍沿用账户原有报价服务。</p><div id="tracking-list"></div></details>
<div class="toolbar"><label>股票<select id="data-symbol"></select></label><label>日期<select id="data-date"></select></label>
<button id="data-refresh">刷新显示</button><button id="data-immediate">查询当前观察</button><button id="data-export">导出表格</button></div>
<details><summary>显示列</summary><button id="columns-full">原版全列</button><button id="columns-common">常用列</button><p>下方勾选自定义列；空值保留为未知。行业涨跌的板块名称与本行历史来源分别标注。</p><div id="data-columns"></div></details>
<h2>观察记录</h2><p>正式五分钟观察与即时观察分别标注。横向滚动可查看更多列。</p><button id="observation-new" hidden>查看新增行</button><div id="observation-scroll"><table id="observation-table"></table></div>
<p>涨跌幅及相对值按自身正负红涨绿跌；价格沿用原版中性展示；Δ量额是区间成交，不是净流入。琥珀色表示待校验。</p><h2>Δ成交额变化（元）</h2><p>与观察表使用同一事实；这是成交额增量，不代表资金净流入。</p><div id="amount-chart"></div>
<h2>原生事件</h2><div id="source-events"></div>
</section><style>#tracking-form{display:flex;gap:12px;flex-wrap:wrap}#tracking-list>div{margin:12px 0}.source-badge{display:inline-block;padding:3px 8px;margin:3px;border-radius:5px}.native-blue{background:#dcecff;color:#174c8f}.important-orange{background:#ffebd1;color:#813e00}.advised-cyan{background:#d6f5f5;color:#005a5a}.expired-grey{background:#e8e8e8;color:#444}#observation-table th,#observation-table td{white-space:nowrap;padding:8px}#amount-chart svg{width:100%;max-height:200px}</style>
<style>#data-observation{max-width:100%;min-width:0}#data-observation>details{background:#fff;border:1px solid #dce3ed;border-radius:12px;padding:16px;margin:16px 0}#data-observation summary{font-weight:650;cursor:pointer}#data-observation button,#data-observation select,#data-observation input:not([type=checkbox]){font:inherit;border:1px solid #b9c9d7;border-radius:7px;padding:8px 12px;background:#fff;color:#17344b;max-width:100%}#data-observation button{cursor:pointer;background:#eff5fa;margin:5px}#data-observation button:hover{background:#dcecf7}#data-observation label{display:inline-flex;align-items:center;gap:6px;margin:5px}#tracking-form label{flex-direction:column;align-items:flex-start}#data-status{padding:14px;background:#edf5f9;border-radius:10px}#data-observation .toolbar{display:flex;flex-wrap:wrap;align-items:center;margin:20px 0}#observation-table{border-collapse:collapse;width:100%;background:#fff}#observation-table th{background:#edf2f6}#observation-table td{border-bottom:1px solid #e5ebf1}#data-columns{display:flex;flex-wrap:wrap}#amount-chart{background:#fff;border:1px solid #e0e8ef;border-radius:12px;padding:12px}</style>
<style>#observation-scroll{height:min(52vh,480px);overflow:auto;overflow-anchor:none;border:1px solid #dce3ed}#observation-table{width:max-content;min-width:100%;font-variant-numeric:tabular-nums;table-layout:fixed}#observation-table th{position:sticky;top:0;z-index:2}#observation-table th:first-child,#observation-table td:first-child{position:sticky;left:0;background:#f1f5fa;z-index:1}#observation-table th:first-child{z-index:3}#observation-table td{max-width:210px;overflow:hidden;text-overflow:ellipsis;text-align:right;font-size:13px}#observation-table .market-up{color:#b92b38}#observation-table .market-down{color:#157b51}#observation-table .quality-pending{color:#855000;background:#fff1cf}.severity-info{color:#496278;background:#eaf0f5}.severity-watch{color:#205c9b;background:#e6f0fc}.severity-important{color:#855000;background:#fff1cf}.severity-critical{color:#943b00;background:#ffdfbc;font-weight:bold}#source-events{max-height:300px;overflow:auto}</style>
<link rel="stylesheet" href="/assets/history.css"><script src="/assets/reading-format.js" defer></script><script src="/assets/history.js" defer></script><script src="/assets/display-refresh.js" defer></script><script src="/assets/data-observation.js" defer></script>'''

def create_module(client):
    return Module('data_observation','数据观察','/data-observation','行情与原生观察',lambda:HealthCheck('market_agent','Market Data Agent','RESERVED','唯一正式行情源：Market Data Agent；健康以实际连接状态为准'),lambda:Page('跟踪设置与后台采集',(),content_html=HTML))

class ObservationRouter:
    def __init__(self,client,advised=None,active_source=None,deletion=None):self.client=client;self.advised=advised or (lambda symbol:None);self.active_source=active_source;self.read_model=None;self.deletion=deletion
    def start_observation_model(self,path):
        from engines.live.read_model import LiveReadModel
        from contextlib import nullcontext
        def collect():
            with self.active_source.read_scope() if self.active_source else nullcontext():
                status,value,_=self.route('GET','/api/data-observation/state')
            if status!=200:raise ValueError(value.get('message','观察读模型暂不可用'))
            return self._display(value,{'view':'display'})
        self.read_model=LiveReadModel(path,collect);self.read_model.start()
    def close(self):
        if self.read_model:self.read_model.close()
    def accepts_post(self,path):return path in ('/api/data-observation/commands','/api/data-observation/metadata')
    def route(self,method,path,payload=None):
        if method=='GET' and path=='/assets/data-observation.js':return 200,Path(__file__).with_name('static').joinpath('data-observation.js').read_bytes(),'text/javascript; charset=utf-8'
        if not path.startswith('/api/data-observation/'):return None
        try:
            if method=='GET' and path=='/api/data-observation/state':
                if self.read_model and (payload or {}).get('view')=='display':
                    value=self.read_model.read()
                    if self.deletion:value=self.deletion.filter_current(value)
                    if self.active_source and any(value.get(k)!=v for k,v in self.active_source.identity().items()):
                        return 200,{'status':'INITIAL_LOADING','message':'数据源已变化，正在读取新来源；旧来源内容不再显示。',**self.active_source.identity()},None
                    return 200,self._display(value,payload),None
                if self.client.root is None:return 503,{'status':'NOT_CONNECTED','error':'AGENT_NOT_CONFIGURED','message':'Market Data Agent 数据目录未配置。'},None
                value=self.active_source.observation_state() if self.active_source else self.client.query();badges={}
                opinions={s['symbol']:self.advised(s['symbol']) for s in value['sessions']}
                for fact in value['facts']:
                    if fact['kind']!='EVENT':continue
                    e=fact['payload'];opinion=opinions.get(e['symbol']) or {}
                    badges[e['event_id']]={'advised':opinion.get('tracking_session_id')==e['tracking_session_id'] and (opinion.get('input_event_seq_to') or 0)>=e['event_seq'],
                        'validity':value.get('event_statuses',{}).get(e['event_id'],'EXPIRED')}
                value['event_badges']=badges
                return 200,self._display(value,payload),None
            command = {'/api/data-observation/commands':'command','/api/data-observation/metadata':'metadata'}.get(path)
            if method=='POST' and command:
                if command=='command' and (payload or {}).get('action') in ('DELETE','DELETE_PLAN'):
                    if not self.deletion or payload['action']!='DELETE':raise AgentError('DELETE_SERVICE_UNAVAILABLE')
                    return 200,self.deletion.delete(payload),None
                if command=='command' and (payload or {}).get('action')=='RESERVE_SESSIONS':raise AgentError('SYSTEM_COMMAND_ONLY')
                return 200,self.active_source.agent_command(command,payload) if self.active_source else getattr(self.client,command)(payload),None
            return 404,{'error':'DATA_OBSERVATION_ENDPOINT_NOT_FOUND'},None
        except AgentError as e:return e.status,{'error':e.code,'message':str(e),'status':'NOT_CONNECTED'},None

    @staticmethod
    def _display(value,payload):
        if (payload or {}).get("view")!="display" or not value.get("sessions"):return value
        # Omit duplicated session row arrays and protocol facts from the ordinary table.
        # Owner readers retain the complete value contract above.
        value['sessions']=[{k:v for k,v in s.items() if k!='rows'} for s in value['sessions']]
        value['facts']=[f for f in value['facts'] if f['kind'] in ('OBSERVATION','EVENT')]
        revision=hashlib.sha256(json.dumps([value.get('source_generation'),value['source'],value['version'],value.get('fact_version'),value['event_badges']],sort_keys=True).encode()).hexdigest()
        value['display_revision']=revision
        if (payload or {}).get('since')==revision:
            value={k:v for k,v in value.items() if k not in ('facts','sessions','analysis_state','event_statuses','event_badges')}
            value['unchanged']=True
        else:
            value.pop('analysis_state',None);value.pop('event_statuses',None)
        return value
