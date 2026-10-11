/* Compatibility bootstrap: an already-running Web serves this asset from disk. */
if(!window.TradingLabDisplayRefresh){
/* Display-only lifecycle. Never abort commands or stop a producer. */
(()=>{'use strict';
window.TradingLabDisplayRefresh=class {
  constructor(read,{period=2500,maxDelay=30000,onError=()=>{},onPause=()=>{}}={}){
    this.read=read;this.period=period;this.maxDelay=maxDelay;this.onError=onError;this.onPause=onPause;
    this.flight=null;this.timer=null;this.requests=new Map();this.failures=0;this.stopped=false;
    this.visibility=()=>document.hidden?this.pause():this.refresh();
    this.hide=()=>{this.stopped=true;this.pause();};this.show=()=>{this.stopped=false;this.refresh();};
    document.addEventListener('visibilitychange',this.visibility);window.addEventListener('pagehide',this.hide);window.addEventListener('pageshow',this.show);
  }
  active(){return !this.stopped&&!document.hidden;}
  pause(){clearTimeout(this.timer);this.timer=null;this.onPause();for(const entry of this.requests.values())entry.controller.abort(new DOMException('Display hidden','AbortError'));}
  request(url,timeout=6000){
    if(this.requests.has(url))return this.requests.get(url).promise;
    if(!this.active())return Promise.reject(new DOMException('Display inactive','AbortError'));
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(new DOMException('Display read timed out','TimeoutError')),timeout);
    const entry={controller};entry.promise=fetch(url,{signal:controller.signal}).then(async r=>{const value=await r.json();if(!r.ok){const e=Error(value.message||value.error||`HTTP ${r.status}`);e.code=value.error;throw e;}return value;}).finally(()=>{clearTimeout(timer);if(this.requests.get(url)===entry)this.requests.delete(url);});
    this.requests.set(url,entry);return entry.promise;
  }
  refresh(){
    clearTimeout(this.timer);this.timer=null;
    if(!this.active())return Promise.resolve();
    if(this.flight)return this.flight;
    this.flight=Promise.resolve().then(()=>this.read()).then(ok=>{this.failures=ok===false?Math.min(this.failures+1,5):0;}).catch(e=>{if(this.active()&&e.name!=='AbortError'){this.failures=Math.min(this.failures+1,5);this.onError(e);}}).finally(()=>{
      this.flight=null;
      if(this.active())this.timer=setTimeout(()=>this.refresh(),Math.min(this.maxDelay,this.period*2**this.failures));
    });return this.flight;
  }
};
})();

}
(()=>{'use strict';const $=id=>document.getElementById(id);let current=null,pending=false,revision=0,committedVersion=0,lastSourceGeneration=null;
const columns=[['requestedTime','输出时点'],['interval','统计区间'],['open','区间开盘'],['high','区间最高'],['low','区间最低'],['price','当前价'],['cumulativeVolume','累计成交量'],['deltaVolume','Δ成交量'],['amount','累计成交额（原始）'],['amountQuality','成交额状态'],['deltaAmount','Δ成交额'],['turnover','累计换手'],['deltaTurnover','Δ换手'],['vwap','累计VWAP'],['intervalVwap','区间VWAP'],['stockChange','个股涨跌'],['boardChange','行业涨跌'],['shanghai','上证'],['chinext','创业'],['beijing','北交'],['star','科创'],['volumeRatio','同时段量比'],['vwapGap','现价-VWAP%'],['intervalChange','区间涨跌'],['priceEfficiency','价格推动效率%/1pp换手'],['alpha','个股-行业Alpha'],['boardMedianChange','行业宽度 · 成分股中位数'],['events','事件标签'],['source','观察类型'],['stockDataTime','市场数据截至'],['capturedAt','最近获取']];
const common=['requestedTime','price','deltaAmount','vwap','stockChange','boardChange','alpha','events'];
let savedColumns;try{savedColumns=JSON.parse(localStorage.getItem('market-observation-columns'));}catch{}
const visible=new Set(Array.isArray(savedColumns)?savedColumns:columns.map(x=>x[0])),scrollPositions=new Map();let viewKey='',lastChart='',lastEvents='',preferenceScope='';
const txt=(tag,value)=>{const n=document.createElement(tag);n.textContent=value??'—';return n;};
async function api(path,value){if(value===undefined)return displayRefresh.request(path,5000);const r=await fetch(path,{method:value?'POST':'GET',headers:value?{'Content-Type':'application/json'}:{},body:value?JSON.stringify(value):undefined,signal:AbortSignal.timeout(value?100000:5000)});const data=await r.json();if(!r.ok)throw Error(data.message||data.error);return data;}
function options(node,values){if(document.activeElement===node)return;const selected=node.value,signature=JSON.stringify(values);if(node.dataset.signature===signature)return;node.dataset.signature=signature;node.replaceChildren(...values.map(([v,n])=>{const o=txt('option',n);o.value=v;return o}));if(values.some(v=>v[0]===selected))node.value=selected;}
function rows(){if(!current)return[];const ids=new Set(current.sessions.filter(s=>s.symbol===$('data-symbol').value&&s.date===$('data-date').value).map(s=>s.tracking_session_id));return current.facts.filter(f=>f.kind==='OBSERVATION'&&ids.has(f.payload.tracking_session_id)).map(f=>({...f.payload.raw,_identity:f.identity,_revision:f.revision})).sort((a,b)=>a.requestedTime.localeCompare(b.requestedTime)||a._identity.localeCompare(b._identity));}
function cellValue(r,k){
 if(k==='interval')return `${r.intervalStart||'—'}–${r.intervalEnd||'—'}`;
 if(k==='events')return (r.eventTags||[]).join('、')||'—';
 if(k==='source')return r.source==='auto'?'正式':'即时';
 if(k==='amountQuality')return r.amount==null?'缺失':r.amountTrusted===false?'待校验':r.amountTrusted===true?'已校验':'质量未知';
 if(r[k]==null)return '—';if(typeof r[k]!=='number')return r[k];
 if(['cumulativeVolume','deltaVolume'].includes(k))return readingFormat.volume(r[k])+' 股';
 const percent=['turnover','stockChange','boardChange','shanghai','chinext','beijing','star','vwapGap','intervalChange','boardMedianChange'].includes(k);
 const unit=percent?'%':k==='alpha'||k==='deltaTurnover'?' pp':k==='volumeRatio'?' 倍':k==='amount'||k==='deltaAmount'?' 元':k==='cumulativeVolume'||k==='deltaVolume'?' 股':'';
 return r[k].toLocaleString('zh-CN',{maximumFractionDigits:['cumulativeVolume','deltaVolume'].includes(k)?0:2,minimumFractionDigits:0})+unit;
}
function saveColumns(){localStorage.setItem(preferenceScope+'columns',JSON.stringify([...visible]));for(const c of $('data-columns').querySelectorAll('input'))c.checked=visible.has(c.dataset.column);render();}
function render(){if(!current)return;const values=rows(),table=$('observation-table'),scroll=$('observation-scroll'),nextKey=[current.source,current.source_generation,$('data-symbol').value,$('data-date').value].join('|');
const switched=viewKey!==nextKey;if(switched&&viewKey)scrollPositions.set(viewKey,[scroll.scrollTop,scroll.scrollLeft]);
const following=scroll.scrollHeight-scroll.scrollTop-scroll.clientHeight<24,top=scroll.scrollTop,left=scroll.scrollLeft;
const session=current.sessions.find(s=>s.symbol===$('data-symbol').value&&s.date===$('data-date').value),board=session?.selectedBoardName,boardCode=session?.selectedBoardCode;
const labels=columns.filter(([k])=>visible.has(k)).map(([k,label])=>[k,k==='boardChange'?`行业涨跌 · ${board||'板块未确认'}`:k==='volumeRatio'?`同时段量比（${current.parameters?.volume_ratio_days||20}日）`:label]);
let head=table.tHead;if(!head){head=table.createTHead();head.insertRow();table.createTBody();}const headerKey=JSON.stringify(labels);
if(head.dataset.key!==headerKey){head.dataset.key=headerKey;head.rows[0].replaceChildren(...labels.map(([k,label])=>{const th=txt('th',label);th.dataset.column=k;return th;}));}
const tbody=table.tBodies[0],existing=new Map([...tbody.rows].map(r=>[r.dataset.identity,r]));let added=0;const retained=new Set();
for(const r of values){let tr=existing.get(r._identity);if(!tr){tr=document.createElement('tr');tr.dataset.identity=r._identity;added++;}retained.add(tr);
const signature=JSON.stringify([r,labels,boardCode]);if(tr.dataset.signature!==signature){tr.dataset.signature=signature;
while(tr.cells.length<labels.length)tr.insertCell();while(tr.cells.length>labels.length)tr.deleteCell(-1);
labels.forEach(([k],i)=>{const td=tr.cells[i];let value=cellValue(r,k);const historical=k==='boardChange'||k==='alpha'||k==='boardMedianChange';
const origin=k==='boardMedianChange'?(r.boardMedianCode||null):r.boardCode;
if(historical&&(origin!==boardCode||!origin))value+=` · ${origin?(r.boardName||origin):'历史板块未知'}`;
td.textContent=value;td.dataset.column=k;td.className='';td.title=historical?`本行来源 ${origin||'未知'}；${r.boardName||'名称未保存'}；按记录时口径展示`:k==='amountQuality'?(r.vwapIssue||'原始成交额保留；成交额增量不代表资金净流入'):String(value);
if(k==='amountQuality'&&r.amountTrusted===false)td.className='quality-pending';
if(['stockChange','boardChange','shanghai','chinext','beijing','star','vwapGap','intervalChange','priceEfficiency','alpha','boardMedianChange'].includes(k)&&typeof r[k]==='number')td.className=r[k]>0?'market-up':r[k]<0?'market-down':'';
});}if(tbody.rows[[...retained].length-1]!==tr)tbody.insertBefore(tr,tbody.rows[[...retained].length-1]||null);}
for(const tr of [...tbody.rows])if(!retained.has(tr))tr.remove();viewKey=nextKey;
if(switched){const saved=scrollPositions.get(viewKey)||[0,0];scroll.scrollTop=saved[0];scroll.scrollLeft=saved[1];$('observation-new').hidden=true;}
else{scroll.scrollLeft=left;if(following&&added)scroll.scrollTop=scroll.scrollHeight;else{scroll.scrollTop=top;if(added){$('observation-new').textContent=`新增 ${added} 行 · 查看最新`;$('observation-new').hidden=false;}}}
const points=values.filter(r=>Number.isFinite(r.deltaAmount)),chart=$('amount-chart'),chartKey=JSON.stringify(points.map(r=>[r._identity,r.requestedTime,r.deltaAmount]));
if(chartKey!==lastChart){lastChart=chartKey;const ns='http://www.w3.org/2000/svg';let svg=chart.querySelector('svg');if(!svg){chart.replaceChildren();svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 800 180');svg.setAttribute('role','img');svg.setAttribute('aria-label','观察记录成交额增量变化（元）');const poly=document.createElementNS(ns,'polyline');poly.setAttribute('fill','none');poly.setAttribute('stroke','#2878b8');poly.setAttribute('stroke-width','3');svg.append(poly);chart.append(svg);}const max=Math.max(1,...points.map(r=>Math.abs(r.deltaAmount)));svg.querySelector('polyline').setAttribute('points',points.map((r,i)=>`${20+i*760/Math.max(1,points.length-1)},${90-r.deltaAmount/max*70}`).join(' '));
let dots=[...svg.querySelectorAll('circle')];points.forEach((r,i)=>{let dot=dots[i];if(!dot){dot=document.createElementNS(ns,'circle');dot.setAttribute('r','4');dot.setAttribute('fill','#2878b8');dot.append(document.createElementNS(ns,'title'));svg.append(dot);}dot.setAttribute('cx',String(20+i*760/Math.max(1,points.length-1)));dot.setAttribute('cy',String(90-r.deltaAmount/max*70));dot.querySelector('title').textContent=r.requestedTime+' · '+r.deltaAmount+' 元';});for(const dot of dots.slice(points.length))dot.remove();}
const rawEvents=current.facts.filter(f=>f.kind==='EVENT'&&f.payload.symbol===$('data-symbol').value&&f.payload.session_date===$('data-date').value),eventKey=JSON.stringify([rawEvents,current.event_badges]);
if(lastEvents!==eventKey){lastEvents=eventKey;const events=$('source-events');events.replaceChildren();for(const f of rawEvents){const e=f.payload,n=txt('p',`${e.timestamp} ${e.label||e.type} · ${e.price??'—'} `),b=current.event_badges?.[e.event_id]||{},sev=e.severity||'INFO';const badge=(label,cls)=>{const span=txt('span',label);span.className='source-badge '+cls;n.append(span)};badge(({INFO:'普通记录',WATCH:'值得关注',IMPORTANT:'重点关注',CRITICAL:'⚠ 严重警示'})[sev]||sev,'severity-'+sev.toLowerCase());badge(b.advised?'已分析':'未分析',b.advised?'advised-cyan':'native-blue');if(['EXPIRED','SUPERSEDED'].includes(b.validity))badge(b.validity==='EXPIRED'?'已过期':'已替代','expired-grey');events.append(n);}}
}
async function command(value){if(current?.read_model&&current.read_model.refresh_state!=='CURRENT')throw Error('当前显示上次成功记录，等待后台恢复后再操作。');if(!current)throw Error('后台状态未就绪');const result=await api('/api/data-observation/commands',{schema_version:'1.0',command_id:crypto.randomUUID(),source:current.source,expected_version:current.version,...value});committedVersion=Math.max(committedVersion,result.version);current.version=committedVersion;await refresh();return result;}
function refresh(){return displayRefresh.refresh();}
async function refreshNow(){if(pending)return;pending=true;const seq=++revision;try{let value=await api('/api/data-observation/state?view=display'+(current?.display_revision?'&since='+encodeURIComponent(current.display_revision):''));if(value.unchanged&&current)value={...current,...value};if(lastSourceGeneration!==value.source_generation){committedVersion=0;lastSourceGeneration=value.source_generation;}if(seq!==revision||value.version<committedVersion)return;if(['INITIAL_LOADING','NOT_CONFIGURED','LEGACY_READ_ONLY'].includes(value.status)){current=null;viewKey='';lastChart='';lastEvents='';$('data-status').textContent=value.message;for(const id of ['observation-table','source-events','amount-chart','tracking-list'])$(id).replaceChildren();return;}const scope='observation:'+location.origin+':'+value.source+':'+value.source_generation+':';if(preferenceScope!==scope){preferenceScope=scope;try{const saved=JSON.parse(localStorage.getItem(scope+'columns'));if(Array.isArray(saved)){visible.clear();saved.forEach(k=>visible.add(k));}}catch{}}current=value;$('data-status').textContent=`数据源：Market Data Agent · ${value.source==='TEST'?'隔离测试 · ':''}后台${value.agent_state==='RUNNING'?'运行中':'已停止'} · 最近采集 ${value.last_cycle_at||'尚未采集'}${value.errors.length?' · '+value.errors.map(e=>e.message).join('；'):''}`;
options($('data-symbol'),[...new Map(value.sessions.map(s=>[s.symbol,[s.symbol,`${s.stockName||s.symbol} ${s.symbol}`]])).values()]);options($('data-date'),[...new Set(value.sessions.map(s=>s.date))].sort().reverse().map(s=>[s,s]));
if(value.read_model)$('data-status').textContent+=` · 最近整理 ${value.read_model.collected_at} · ${value.read_model.refresh_state==='CURRENT'?'已更新':'保留上次成功记录，当前状态待核对'}`;if(!viewKey){const saved=localStorage.getItem(preferenceScope+'symbol');if([...$('data-symbol').options].some(o=>o.value===saved))$('data-symbol').value=saved;}const list=$('tracking-list'),signature=JSON.stringify(value.sessions.map(s=>[s.tracking_session_id,s.lifecycle_status,s.stockName]));if(list.dataset.signature!==signature){list.dataset.signature=signature;list.replaceChildren(...value.sessions.filter(s=>s.date===value.trading_date).map(s=>{const n=txt('div',`${s.stockName||s.symbol} ${s.symbol} · ${{ACTIVE:'跟踪中',PAUSED:'暂停重点观察（仍采集）',DROPPED:'已停止'}[s.lifecycle_status]||s.lifecycle_status} `);for(const [action,label]of (s.lifecycle_status==='DROPPED'?[['DELETE','删除']]:[['PAUSE','暂停重点观察'],['RESUME','继续重点观察'],['DELETE','删除']])){const b=txt('button',label);b.onclick=()=>{if(action==='DELETE'&&!confirm('删除此股票的跟踪与 Live 工作数据？将先备份；账户账本、已保存AI意见及其证据、必要引用保留。暂停重点观察仍可单独使用。'))return;command({action,symbol:s.symbol,...(action==='DELETE'?{confirmation:'DELETE_TRACKING_DATA'}:{})}).catch(e=>$('data-status').textContent=e.message);};n.append(b);}return n;}));}render();}catch(e){if(seq===revision)$('data-status').textContent=e.message+'；保留已显示记录。';return false;}finally{pending=false;}}
for(const [key,label]of columns){const l=document.createElement('label'),c=document.createElement('input');c.type='checkbox';c.dataset.column=key;c.checked=visible.has(key);c.onchange=()=>{c.checked?visible.add(key):visible.delete(key);saveColumns();};l.append(c,txt('span',label));$('data-columns').append(l);}
$('tracking-form').onsubmit=async e=>{e.preventDefault();const form=e.target,f=new FormData(form),button=form.querySelector('button:not([type=button])');button.disabled=true;try{await command({action:'ADD',symbol:f.get('symbol'),name:f.get('name'),board:{code:f.get('board_code'),name:f.get('board_name')}});if([...f].every(([k,v])=>form.elements.namedItem(k)?.value===v))form.reset();}catch(error){$('data-status').textContent=error.message;}finally{button.disabled=false;}};
$('data-symbol').onchange=()=>{localStorage.setItem(preferenceScope+'symbol',$('data-symbol').value);render();};$('data-date').onchange=render;
$('observation-new').onclick=()=>{$('observation-scroll').scrollTop=$('observation-scroll').scrollHeight;$('observation-new').hidden=true;};$('columns-full').onclick=()=>{visible.clear();columns.forEach(([k])=>visible.add(k));saveColumns();};$('columns-common').onclick=()=>{visible.clear();common.forEach(k=>visible.add(k));saveColumns();};$('data-refresh').onclick=refresh;$('data-export').onclick=()=>{const q=v=>'"'+String(v??'').replaceAll('"','""')+'"',body=[columns.map(c=>q(c[1])).join(','),...rows().map(r=>columns.map(([k])=>q(cellValue(r,k))).join(','))].join('\r\n');const a=document.createElement('a');a.href=URL.createObjectURL(new Blob(['\uFEFF'+body],{type:'text/csv'}));a.download='observations.csv';a.click();URL.revokeObjectURL(a.href);};
let boards=[];const field=name=>$('tracking-form').elements.namedItem(name);
$('lookup-stock').onclick=async()=>{try{const data=await api('/api/data-observation/metadata',{schema_version:'1.0',source:current?.source,symbol:field('symbol').value});field('name').value=data.profile?.name||data.boards?.name||'';boards=Array.isArray(data.boards)?data.boards:data.boards?.boards||[];options($('lookup-board'),[['','请选择板块'],...boards.map(b=>[b.code,b.name])]);}catch(e){$('data-status').textContent=e.message;}};
$('lookup-board').onchange=()=>{const b=boards.find(b=>b.code===$('lookup-board').value);if(b){field('board_code').value=b.code;field('board_name').value=b.name;}};
$('update-board').onclick=()=>command({action:'BOARD',symbol:field('symbol').value,name:field('name').value,board:{code:field('board_code').value,name:field('board_name').value}}).catch(e=>$('data-status').textContent=e.message);
$('save-parameters').onclick=()=>command({action:'PARAMETERS',volume_ratio_days:Number($('volume-days').value)}).catch(e=>$('data-status').textContent=e.message);
$('data-immediate').onclick=()=>command({action:'IMMEDIATE',symbol:$('data-symbol').value}).catch(e=>$('data-status').textContent=e.message);
const displayRefresh=new TradingLabDisplayRefresh(refreshNow,{period:2500,onPause:()=>{revision++;}});refresh();})();
