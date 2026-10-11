(() => {
  'use strict';
  // A historical result view must not poll, mark read or change the real-time view.
  if(/^HIST-[a-f0-9]{32}$/.test(new URLSearchParams(location.search).get('history')||''))return;
  const $=id=>document.getElementById(id);if(!$('live-center'))return;
  let state=null,busy=false,refreshRevision=0,globalSettingsDirty=false,versionChecked=false,settingsFlight=null,nextSettingsAt=0,settingsFailures=0;
  const labels={SNAPSHOT_WITHOUT_STRUCTURE:'实时行情可用 · 周期观察缺失',CLOSE_COMPLETE:'收盘时点已到（不代表指标全部可信）',CLOSE_TAIL_MISSING:'收盘尾段缺失',LUNCH_BREAK:'午间休市',WAITING_FIRST_DATA:'等待首条数据',OBSERVATION_MISSING:'缺少连续观察',NON_TRADING_DAY:'非交易日',BEFORE_OPEN:'开盘前',TRADING:'交易时段',CLOSED:'已收盘',CALENDAR_UNKNOWN:'交易日状态未知',WATCHING:'运行中',STARTING:'启动中',STOPPED:'未启动',RUNNING_NO_SOURCE:'监听中 · 等待源数据',RUNNING_SYNCED:'运行正常',RUNNING_PENDING:'正在同步新事实',RUNNING_LAGGING:'Live事实同步落后',SOURCE_STALE:'行情时效需检查',SOURCE_ERROR:'数据源异常',PAUSED_PROVIDER_ERROR:'AI配置不可用',CONNECTED:'已连接',TRACKED:'跟踪中',ACTIVE:'跟踪中',SOURCE_ALREADY_COVERED:'来源已被V2A覆盖',SOURCE_CURSOR_ADVANCED:'已确认游标推进',SOURCE_INVALIDATED:'来源已失效',SOURCE_MUTATED:'严重来源变更',SOURCE_UNAVAILABLE:'来源暂不可读',SOURCE_WINDOW_EXTENDED:'后续市场窗口扩展',FRESH:'新鲜',DELAYED:'延迟',STALE:'陈旧',UNKNOWN:'未知',ARCHIVED:'历史Decision已归档',WAITING_ANALYZABLE_EVENT:'等待可分析事件',PROTOCOL_UNMAPPABLE:'协议不可安全映射',WAITING_HUMAN_REVIEW:'待人工审核',WAITING_V2A_IMPORT:'等待V2A人工导入',AI_READY:'待人工审核',REVIEWED:'已审核',WAITING_V2A:'待V2A确认',CONSUMED:'回执已消费',QUEUED:'待处理',RUNNING:'分析中',IDLE:'空闲',DONE:'已完成',FAILED:'失败待重试',NOT_CONNECTED:'未连接',READY:'就绪',MARKET_CLOSED:'闭市',OFF:'关闭',IMPORTANT_ONLY:'仅重要事件',ALL_EVENTS:'所有已选事件'};
  const actionText={NO_ACTION:'观察',WATCH:'观察',WAIT:'等待',HOLD:'维持',ADD:'增加',REDUCE:'降低',EXIT:'退出'};
  const sideText={BUYER:'买方',SELLER:'卖方',BALANCED:'平衡',UNCLEAR:'不明确'};
  const trendText={STRENGTHENING:'增强',WEAKENING:'减弱',STABLE:'稳定',REVERSING:'反转',UNCLEAR:'不明确'};
  const reviewText={CONFIRMED:'确认',STRENGTHENED:'增强但未确认',WEAKENED:'减弱',INVALIDATED:'已失效',UNCHANGED:'保持不变',INSUFFICIENT_EVIDENCE:'证据不足'};
  const business={LIVE_SHADOW:'影子账户',ai_execution_mode:'账户执行策略',previous_advisory:'上一轮意见',priceEfficiency:'价格推动效率',NEEDS_SIZING:'尚未确定目标仓位',MARKET_EVIDENCE_INCOMPLETE:'市场证据不完整',BLOCKED:'暂未执行',ADVISORY_ONLY:'只给模拟交易建议'};
  const readingWords={...window.readingFormat?.terms,...labels,...actionText,...sideText,...trendText,...reviewText,...business,
    'FAILED WINDOW':'失败分析窗口',FAILED_WINDOW:'失败分析窗口',FAILED:'失败',INVALID:'无效',INPUT_BUDGET:'输入预算不足',
    INPUT:'输入构建',CONFIGURATION:'配置',PROVIDER:'AI服务',SCHEMA:'响应格式',PERSISTENCE:'结果保存',
    TIMEOUT:'请求超时',NETWORK_ERROR:'网络异常',MODEL_INVALID:'模型请求被拒绝',NO_NEW_DATA:'没有新数据',
    PROVIDER_TIMEOUT:'AI服务请求超时',PROVIDER_NETWORK_ERROR:'AI服务网络异常',PROVIDER_ERROR:'AI服务异常',
    PROVIDER_PARSE_ERROR:'AI返回内容无法解析',PROVIDER_SCHEMA_ERROR:'AI返回内容不符合格式',
    DAILY_PROVIDER_FAILED:'AI服务请求失败',ADVISORY_PROVIDER_ERROR:'AI分析服务异常',
    API_KEY_MISSING:'未配置服务密钥',AUTH_FAILED:'AI服务认证失败',PROVIDER_NOT_CONFIGURED:'AI服务尚未配置',
    MODEL_NOT_SUPPORTED:'模型暂不支持',ADVISORY_SCHEMA_ERROR:'分析结果格式不符合要求',INVALID_JSON:'返回格式无效',
    MANUAL:'手动',AUTO_EVENT:'事件自动',MANUAL_REANALYSIS:'手动重新分析',SUCCEEDED:'分析成功',
    SUPERSEDED:'已被新结果替代',CANCELLED:'已取消',ERROR:'异常',INFO:'普通记录',NOTICE:'值得关注',IMPORTANT:'重点关注',CRITICAL:'严重警示',
    LOW:'低',MEDIUM:'中',HIGH:'高',NEUTRAL:'中性',OPEN:'建仓',NONE:'不行动',
    NEW_HIGH:'新高',NEW_LOW:'新低',VWAP_RECLAIM:'重回VWAP上方',VWAP_LOST:'跌破VWAP',SUPPORT_RETEST:'支撑二测',
    FADE_DOWN:'冲高回落',LOW_VOLUME_PULLBACK:'缩量回踩',RECLAIM_CONTINUE:'收复后延续',LOW_LEVEL_CONSOLIDATION:'低位整理',
    BREAKOUT_UP:'向上突破',CONSOLIDATION:'整理',WEAKENING_DOWN:'转弱下行',PRICE_EFFICIENCY_DECAY:'价格效率衰减',
    BREAKOUT_HOLD:'突破后守稳',HIGH_LEVEL_CHURN:'高位震荡',BREAKOUT_CONTINUE:'突破延续',HIGH_LEVEL_CONSOLIDATION:'高位整理',
    price_vwap_pct:'价格与VWAP偏离',price_efficiency:'价格效率',priceEfficiency:'价格效率',
    delta_volume:'增量成交量',deltaVolume:'增量成交量',delta_amount:'增量成交额',deltaTurnover:'增量换手',delta_alpha:'alpha变化',
    volumeRatio:'量比',volume_ratio:'量比',delta_since_previous:'相比上一轮',snapshot_path:'实时行情路径',
    delta:'增量',volume:'成交量',pct:'涨跌幅',severity:'重要程度',demand:'需求',efficiency:'效率',seq:'序号',
    Provider:'AI服务',SIMULATION:'模拟回放',FIXTURE:'测试AI',CONFIGURED:'已配置服务',
    none:'关闭额外思考',low:'低',high:'高',max:'最高','N/A':'暂无'};
  const readingPattern=new RegExp('(?<![A-Za-z0-9_])('+Object.keys(readingWords).sort((a,b)=>b.length-a.length).map(k=>k.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')).join('|')+')(?![A-Za-z0-9_])','g');
  const chinese=value=>typeof value==='string'?value.replace(readingPattern,k=>readingWords[k]):value;
  const label=value=>readingWords[value]||chinese(value)||'未知';
  const text=(tag,value,cls)=>{const node=document.createElement(tag);node.textContent=chinese(value)??'—';if(cls)node.className=cls;return node;};
  async function api(path,body,method){if(body===undefined)return displayRefresh.request(path,6000);if(body!==undefined){refreshRevision++;nextSettingsAt=0;}const r=await fetch(path,{method:method||(body===undefined?'GET':'POST'),headers:body===undefined?{}:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body),signal:AbortSignal.timeout(body===undefined?6000:120000)});let data;try{data=await r.json();}catch{throw Error(`服务响应异常（HTTP ${r.status}，${path}），请检查服务是否已启动。`);}if(!r.ok){const upstream=Number.isInteger(data.failure?.http_status)?`；AI服务返回 HTTP ${data.failure.http_status}`:'';const e=Error(chinese(data.message||label(data.error)||'请求未完成')+upstream);e.code=data.error;e.failure=data.failure;throw e;}return data;}
  async function act(path){if(busy)return;busy=true;try{await api(path,{});await refresh();}catch(e){$('live-status').textContent=chinese(e.message);}finally{busy=false;}}
  function button(title,handler,cls){const node=text('button',title,cls);node.type='button';node.onclick=handler;return node;}
  function detail(title,value,cls){const node=document.createElement('details');if(cls)node.className=cls;node.append(text('summary',title),text('pre',JSON.stringify(value,null,2)));return node;}
  function options(select,rows,value){const sig=JSON.stringify([rows,value]);if(select.dataset.options===sig||select===document.activeElement)return;select.dataset.options=sig;select.replaceChildren(...rows.map(row=>{const o=document.createElement('option');o.value=row.value;o.textContent=chinese(row.label);o.selected=row.value===value;return o;}));}
  function models(provider){return state.advisory_settings.catalog.providers.find(row=>row.provider===provider)?.models||[];}
  function configureModel(providerSelect,modelSelect,setting,reasoningSelect){const providers=state.advisory_settings.catalog.providers;options(providerSelect,providers.map(row=>({value:row.provider,label:row.provider})),setting.provider);const effort=()=>{if(!reasoningSelect)return;const p=providers.find(p=>p.provider===providerSelect.value);const values=p?.model_capabilities?.[modelSelect.value]?.reasoning_efforts||state.advisory_settings.reasoning_efforts||[];options(reasoningSelect,values.map(value=>({value,label:value==='low'?'低（推荐）':label(value)})),setting.reasoning_effort);};const sync=()=>{options(modelSelect,models(providerSelect.value).map(value=>({value,label:value})),providerSelect.value===setting.provider?setting.model:null);effort();};providerSelect.onchange=sync;if(modelSelect._effortListener)modelSelect.removeEventListener('change',modelSelect._effortListener);modelSelect._effortListener=effort;modelSelect.addEventListener('change',effort);sync();}
  function fmt(value){if(value===null||value===undefined||value==='')return '—';const raw=String(value);if(raw.includes('T')&&/(Z|[+-]\d\d:\d\d)$/.test(raw)){const date=new Date(raw);if(!Number.isNaN(date.getTime()))return new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).format(date);}return raw;}

  function timeBadge(title,value,cls=''){
    const node=text('span','',`time-badge ${cls}`);node.append(text('span',title,'time-label'),text('time',fmt(value)));
    if(value)node.querySelector('time').dateTime=value;return node;
  }
  // Color is a reading cue; source values and the saved conclusion are never rewritten.
  function directionClass(previous,current,key=''){
    if(key==='risk_level'){
      const rank={LOW:1,MEDIUM:2,HIGH:3,CRITICAL:4,'低':1,'中':2,'高':3,'严重':4};
      previous=rank[previous]??previous;current=rank[current]??current;
    }
    if(typeof previous!=='number'||typeof current!=='number'||!Number.isFinite(previous)||!Number.isFinite(current))return 'change-flat';
    const delta=(current-previous)*(key.includes('risk')?-1:1);return delta>0?'change-up':delta<0?'change-down':'change-flat';
  }
  function prose(value,cls=''){
    const node=text('p','',cls),source=String(chinese(value)??'—');
    const pattern=/[+-]?\d+(?:\.\d+)?%?\s*(?:→|->)\s*[+-]?\d+(?:\.\d+)?%?|(?<![\d/:-])[+-]\d+(?:\.\d+)?%?|增强但未确认|风险增大|风险降低|改善|恶化|增强|减弱|走弱|持平/g;
    let cursor=0;
    for(const match of source.matchAll(pattern)){
      node.append(document.createTextNode(source.slice(cursor,match.index)));const value=match[0];let color='change-flat';
      if(/→|->/.test(value)){const [a,b]=value.split(/→|->/).map(parseFloat);color=directionClass(a,b);}
      else if(/^[+-]\d/.test(value))color=directionClass(0,parseFloat(value));
      else if(!/[未不无]$/.test(source.slice(0,match.index)))color=['增强但未确认','增强','改善','风险降低'].includes(value)?'change-up':['减弱','走弱','恶化','风险增大'].includes(value)?'change-down':'change-flat';
      node.append(text('span',value,color));cursor=match.index+value.length;
    }
    node.append(document.createTextNode(source.slice(cursor)));return node;
  }
  function section(title,cls=''){const node=text('section','',`opinion-section ${cls}`);node.append(text('h4',title));return node;}
  function listText(rows){const node=text('ul','');for(const row of rows||[])node.append(text('li',row));return node;}
  function scenario(value){const node=text('article','','scenario-card');node.append(text('h4',value.label),prose('条件：'+(value.conditions||[]).join('；')),prose('含义：'+(value.interpretation||'—')),prose('建议：'+(value.recommended_action||'—')),prose('确认：'+(value.confirmation||[]).join('；')),prose('失效：'+(value.invalidation||[]).join('；')));return node;}
  function focusView(rows){const list=text('ol','','focus-list');for(const row of rows||[]){const li=text('li','');li.append(text('strong',typeof row==='string'?row:row.target));if(typeof row!=='string')li.append(text('span',` ${row.watch_for} · ${row.meaning}`));list.append(li);}return list;}
  function deltaView(delta){
    const box=text('div','','delta-grid'),number=v=>typeof v==='number'?v.toLocaleString('zh-CN',{maximumFractionDigits:4}):chinese(v)??'—';
    const names={price:'价格',vwap_gap:'VWAP距离',vwap_gap_pct:'VWAP距离%',alpha:'Alpha',volume:'成交量',delta_volume:'增量成交量',delta_amount:'增量成交额',delta_turnover:'增量换手',delta_turnover_pp:'换手变化',volume_ratio:'量比',price_efficiency:'价格效率',dominance_score:'优势分数',confidence:'置信度',target_weight:'建议仓位',risk_level:'风险级别',action:'判断'};
    for(const [key,row] of Object.entries(delta||{})){
      if(!names[key]||!row||typeof row!=='object'||row.previous==null)continue;
      const p=text('p',''),style=directionClass(row.previous,row.current,key);
      const display=v=>key==='target_weight'&&typeof v==='number'?number(v*100)+'%':number(v);
      p.append(text('span',names[key]+'：','delta-label'),text('strong',`${display(row.previous)} → ${display(row.current)}`,style));
      if(typeof row.change==='number')p.append(text('span',` (${row.change>0?'+':''}${key==='target_weight'?number(row.change*100)+'个百分点':number(row.change)})`,style));
      p.append(text('span',style==='change-up'?' ↑':style==='change-down'?' ↓':' · 持平或方向未定',style));box.append(p);
    }
    if(!box.childElementCount)box.append(text('p','暂无可比较的上一轮数值。','empty-note'));return box;
  }
  function opinionView(opinion){
    if(!opinion)return text('section','尚无成功意见。出现新事件后自动分析，或点击“立即分析”。','ai-review empty-note');
    const box=text('section','','opinion-brief'),review=opinion.previous_hypothesis_review||{},seen=new Set();box.dataset.opinionId=opinion.advisory_id;
    const add=(parent,value,cls='')=>{if(value==null||value==='')return;const key=String(value).replace(/\s+/g,' ').trim();if(seen.has(key))return;seen.add(key);parent.append(prose(value,cls));};
    const conclusion=section('本轮结论','opinion-conclusion'),hero=text('div','','judgment-summary');
    hero.append(text('strong',actionText[opinion.action]||label(opinion.action),'judgment-action'));
    if(review.previous_advisory_id){const style=['STRENGTHENED','CONFIRMED'].includes(review.status)?'change-up':['WEAKENED','INVALIDATED'].includes(review.status)?'change-down':'change-flat';hero.append(text('span',reviewText[review.status]||label(review.status),`judgment-review ${style}`));}
    const confidence=text('span',`判断置信度 ${opinion.confidence}%`,'confidence-note');confidence.title='对结构判断的置信度，不是上涨概率或胜率。';hero.append(confidence);conclusion.append(hero);
    const times=text('div','','opinion-times');times.append(timeBadge('本意见数据截至',opinion.data_through_at||opinion.data_through_time,'opinion-cutoff'),timeBadge('最近完成时间',opinion.ai_completed_at||opinion.generated_at));conclusion.append(times);
    add(conclusion,typeof opinion.game_state==='string'?opinion.game_state:opinion.game_state?.summary||opinion.current_state,'opinion-lead');box.append(conclusion);
    const delta=section('相比上一轮','opinion-comparison');delta.append(deltaView(opinion.delta_since_previous));
    if(review.previous_advisory_id){add(delta,review.reason,'hypothesis-review');if(review.previous_action&&review.previous_action!==opinion.action)delta.append(text('p',`判断：${actionText[review.previous_action]||label(review.previous_action)} → ${actionText[opinion.action]||label(opinion.action)}`));}
    else delta.append(text('p','首次分析，暂无上一轮意见可复核。','empty-note'));box.append(delta);
    const basis=section('核心依据','opinion-basis');basis.append(text('p',`${sideText[opinion.dominant_side]||label(opinion.dominant_side)} · 优势分数 ${opinion.dominance_score}/10 · ${trendText[opinion.dominance_trend]||label(opinion.dominance_trend)}`,'dominance-strip'));add(basis,opinion.core_conflict);box.append(basis);
    const focus=section('接下来观察','opinion-focus');focus.append(focusView(opinion.next_observation_focus));box.append(focus);
    const risk=section('风险与失效条件','opinion-risk');risk.append(listText(opinion.invalidation));box.append(risk);
    const more=text('details','','opinion-detail');more.append(text('summary','展开关键证据、条件路径与时间记录'));
    const evidence=section('关键证据');add(evidence,opinion.current_state);for(const row of opinion.evidence||[])add(evidence,row);
    const game=opinion.game_state;if(game&&typeof game==='object')for(const [key,name] of Object.entries({buyer_state:'买方',seller_state:'卖方',absorption_state:'吸收',initiative_side:'主动方',supply_pressure:'供给压力',demand_strength:'需求强度',price_impact_state:'价格推动'}))if(game[key])add(evidence,`${name}：${game[key]}`);
    if(opinion.key_levels?.length){evidence.append(text('h5','关键价位'));for(const level of opinion.key_levels)evidence.append(prose(`${level.label} ${level.price??'暂无'}：${level.meaning}`));}more.append(evidence);
    const paths=section('未来路径 / 条件分支'),grid=text('div','','scenario-grid');for(const row of opinion.scenario_tree||[])grid.append(scenario(row));paths.append(grid);more.append(paths);
    const meta=section('时间记录与分析信息','opinion-metadata');
    meta.append(timeBadge('行情截至',opinion.quote_through_at),timeBadge('结构参考',opinion.structure_through_at));
    const inc=opinion.incremental_window||{start:opinion.incremental_window_start,end:opinion.incremental_window_end},ctx=opinion.context_window||{start:opinion.context_window_start,end:opinion.context_window_end};
    meta.append(text('p',`本轮新增：${fmt(inc.start)} → ${fmt(inc.end)}`),text('p',`参考上下文：${fmt(ctx.start)} → ${fmt(ctx.end)}`),text('p',`触发：${label(opinion.trigger_type)} · 模型：${opinion.provider||'未保存'} / ${opinion.model||'未保存'} · 思考强度：${label(opinion.reasoning_effort)}${opinion.latency_ms!=null?' · 耗时 '+(opinion.latency_ms/1000).toFixed(1)+' 秒':''}`));
    add(meta,opinion.action_semantics?.description);more.append(meta);box.append(more);return box;
  }
  function savedHistory(title,path,key,renderRow,cls){
    const node=text('details','',cls),summary=text('summary',title),content=text('div','','history-content');node.append(summary,content);
    let loading=false,loaded=false,before=null,anchor=null;const pages=[];
    const load=async()=>{if(loading||!node.isConnected)return;loading=true;content.replaceChildren(text('p','正在读取已保存的意见…','history-loading'));
      try{const query=new URL(path,location.origin);query.searchParams.set('limit','10');if(before)query.searchParams.set('before',before);if(anchor)query.searchParams.set('anchor',anchor);
        const data=await api(query.pathname+query.search);if(!node.isConnected)return;const rows=Array.isArray(data[key])?data[key]:[];anchor=data.anchor||anchor;
        content.replaceChildren();if(rows.length)content.append(...rows.map(renderRow));else content.append(text('p',data.message||'当前跟踪暂无历史意见；成功分析保存后会在这里显示。','history-empty'));
        if(pages.length)content.append(button('较新一页',()=>{before=pages.pop();return load();},'history-newer'));
        if(data.next_before)content.append(button('较早一页',()=>{pages.push(before);before=data.next_before;return load();},'history-older'));
        content.append(button('刷新已保存记录',()=>{before=null;anchor=null;pages.length=0;return load();},'history-refresh'));loaded=true;node.dataset.loaded='true';
      }catch(e){if(!node.isConnected)return;content.replaceChildren(text('p','历史记录暂未读取成功，请重试；已保存意见不会丢失。','history-error'),button('重新读取',load,'history-retry'));loaded=false;}
      finally{loading=false;}
    };
    node.addEventListener('toggle',()=>{if(node.open&&!loaded)load();});return node;
  }
  async function acknowledge(card){
    
    return api(`/api/live/${card.session.symbol}/read`,{tracking_session_id:card.session.tracking_session_id,advisory_id:card.latest?.advisory_id||null,event_seq:card.session.source_event_max||0});
  }
  const localFolds=new Map(),foldQueues=new Map();
  function applyFold(node,collapsed){if(!node)return;node.querySelector('.stock-body').hidden=collapsed;node.dataset.collapsed=String(collapsed);const toggle=node.querySelector('.stock-toggle');toggle.textContent=collapsed?'展开':'收起';toggle.setAttribute('aria-expanded',String(!collapsed));toggle.setAttribute('aria-label',collapsed?'展开':'收起');}
  function foldStock(symbol,collapsed){
    localFolds.set(symbol,collapsed);const node=$('stock-'+symbol);applyFold(node,collapsed);
    const previous=foldQueues.get(symbol)||Promise.resolve();
    const task=previous.catch(()=>{}).then(()=>api(`/api/live/${symbol}/preferences`,{collapsed},'PUT'));
    foldQueues.set(symbol,task);task.catch(e=>$('live-status').textContent='展开偏好未保存：'+e.message).finally(()=>{if(foldQueues.get(symbol)===task)foldQueues.delete(symbol);});
    if(!collapsed&&node){const r=node.getBoundingClientRect();if(!document.hidden&&r.top<innerHeight&&r.bottom>0)acknowledge(node._displayedCard).catch(e=>$('live-status').textContent=chinese(e.message));}
    return task;
  }
  // Display-only patching: native details/select/input nodes and their handlers survive polling.
  function patchDisplay(old,next){
    if(old.nodeType===3){if(old.textContent!==next.textContent)old.textContent=next.textContent;return;}
    if(old.matches('select,input,textarea,button,.advisory-message'))return;
    if(old.className!==next.className)old.className=next.className;
    if(old.tagName==='TIME'){if(next.hasAttribute('datetime'))old.dateTime=next.dateTime;else old.removeAttribute('datetime');}
    if(next.dataset.opinionId)old.dataset.opinionId=next.dataset.opinionId;else delete old.dataset.opinionId;
    const a=[...old.childNodes],b=[...next.childNodes];
    for(let i=0;i<b.length;i++){if(!a[i])old.append(b[i]);else if(a[i].nodeType===b[i].nodeType&&a[i].nodeName===b[i].nodeName)patchDisplay(a[i],b[i]);else a[i].replaceWith(b[i]);}
    for(let i=b.length;i<a.length;i++)a[i].remove();
  }
  function patchCard(old,card){
    old._latestCard=card;
    const changedOpinion=old.dataset.advisoryId!==(card.latest?.advisory_id||'');
    if(changedOpinion)for(const panel of old.querySelectorAll('.advisory-history,.advisory-timeline')){
      if(panel.dataset.loaded==='true'&&!panel.querySelector('.history-update'))panel.querySelector('.history-content').prepend(text('p','有新意见，可点击“刷新已保存记录”查看。','history-update'));
    }
    const reading=old.dataset.collapsed==='false';
    const displayed=old._displayedCard;
    const fresh=advisoryCard(reading&&displayed?{...card,latest:displayed.latest}:card,!changedOpinion||reading);
    for(const selector of ['.freshness','.stock-summary','.live-health','.live-events','.sync-summary','.source-notes','.lifecycle-summary']){
      const a=old.querySelector(selector),b=fresh.querySelector(selector);if(a&&b)patchDisplay(a,b);
    }
    const a=old.querySelector('.live-portfolio'),b=fresh.querySelector('.live-portfolio');
    if(a&&b&&a.textContent!==b.textContent)patchDisplay(a,b);
    if(changedOpinion)old.querySelector('.force-reanalysis').hidden=true;
    if(changedOpinion&&!reading){const a=old.querySelector('.opinion-brief,.ai-review'),b=fresh.querySelector('.opinion-brief,.ai-review');if(a&&b)a.replaceWith(b);old.dataset.advisoryId=card.latest?.advisory_id||'';old._displayedCard=card;}
    if(!changedOpinion)old._displayedCard=card;
    let notice=old.querySelector('.new-opinion-notice');
    if(changedOpinion&&reading){if(!notice){notice=button('有新意见，点击查看',()=>{const latest=old._latestCard;const view=opinionView(latest.latest);old.querySelector('.opinion-brief,.ai-review').replaceWith(view);old.dataset.advisoryId=latest.latest?.advisory_id||'';old._displayedCard=latest;const rendered=advisoryCard(latest);const version=rendered.querySelector('.viewed-opinion');old.querySelector('.viewed-opinion')?.replaceWith(version);const portfolio=rendered.querySelector('.live-portfolio');old.querySelector('.live-portfolio')?.replaceWith(portfolio);notice.remove();acknowledge(latest).catch(()=>{});},'new-opinion-notice');old.querySelector('.stock-summary').append(notice);}}
    else notice?.remove();
    applyFold(old,localFolds.has(card.session.symbol)?localFolds.get(card.session.symbol):card.settings.collapsed!==false);
    return old;
  }
  function timelineNode(value){const node=document.createElement('article');node.className='timeline-node';node.append(timeBadge('分析完成',value.generated_at),text('strong',`${actionText[value.action]||value.action} · ${sideText[value.dominant_side]||value.dominant_side} ${value.dominance_score}`),text('span',`${trendText[value.dominance_trend]||value.dominance_trend} · ${reviewText[value.previous_hypothesis_review]||value.previous_hypothesis_review}`),prose(value.summary));return node;}
  function analysisState(card){
    const box=text('section','','analysis-state'),s=card.health?.analysis_status;if(!s)return box;
    const task=s.current_task||{},pending=s.pending||{},latest=s.latest_successful_analysis,why=s.eligibility||{};
    const states={IDLE:'空闲',ELIGIBLE:'等待聚合',QUEUED:'排队中',RUNNING:'分析中',SUCCEEDED:'分析成功',FAILED:'分析失败',NO_NEW_DATA:'没有新数据，无需分析',CONFIRMATION_REQUIRED:'等待确认陈旧数据分析',SUPERSEDED:'旧窗口结果已归档',CANCELLED:'任务已中断'};
    const success=text('div','','latest-success');success.append(timeBadge('最近成功分析截至',latest?.cutoff),timeBadge('最近完成时间',latest?.completed_at));
    box.append(success,
      text('p',`当前任务：${states[task.state]||task.state||'空闲'}${task.frozen_input_cutoff?' · 输入截至 '+fmt(task.frozen_input_cutoff):''}${task.model_config?' · 本任务 '+task.model_config.model+' / '+label(task.model_config.reasoning_effort):''}`,'analysis-task'),
      text('p',`${pending.has_new_data?'已有新数据，尚未分析':'没有尚待分析的新事实'} · 新原生事件 ${pending.new_event_count||0} · 范围匹配 ${pending.matched_event_count??pending.eligible_event_count??0} · 证据合格 ${pending.quality_event_count??pending.eligible_event_count??0} · 可调度 ${pending.eligible_event_count||0} · 即时触发 ${pending.eligible_trigger_count||0} · 未读事件 ${pending.unread_event_count||0}`,'analysis-pending'),
      text('p',(why.reasons?.length?why.reasons.join(' '):why.reason_text)||'等待资格判定','analysis-reason'));
    if(latest)box.querySelector('.latest-success').dataset.opinionId=latest.opinion_id;
    if(s.failure){const f=s.failure,stages={INPUT:'输入构建',CONFIGURATION:'AI配置',PROVIDER:'AI服务',SCHEMA:'AI响应校验',PERSISTENCE:'结果保存',UNKNOWN:'历史记录未区分'};
      box.append(text('p',`本次尝试失败 ${fmt(f.occurred_at||task.finished_at)} · 阶段：${stages[f.stage]||f.stage} · 原因：${f.reason||f.error_code} · 可重试：${f.retryable===true?'是':f.retryable===false?'需先处理原因':'尚未确定'}。${latest?'最近成功意见保留。':'尚无成功意见。'}`,'analysis-failure'));
    }return box;
  }
  function advisoryCard(card,compactUpdate=false){const s=card.session,setting=card.settings,health=card.health||{},fresh=health.v2a||{},node=document.createElement('article');node.className='workspace-panel advisory-card';node.dataset.symbol=s.symbol;node.dataset.advisoryId=card.latest?.advisory_id||'';
    const settingsPath='/api/live/advisory/settings';
    const analyzePath=`/api/live/${s.symbol}/analyze`;
    const timelinePath=`/api/live/${s.symbol}/advisory/timeline`;
    const header=document.createElement('div');header.className='toolbar';header.append(text('h2',`${s.name||s.symbol} · ${s.symbol.replace(/^[a-z]+/,'')}`),timeBadge(label(health.market?.status||fresh.status)+' · 行情截至',health.market?health.market.market_data_time:fresh.latest_data_time,'freshness '+String(fresh.status).toLowerCase()));const pin=button(setting.pin_order===undefined||setting.pin_order===null?'置顶':'取消置顶',async()=>{const latest=node._latestCard||node._displayedCard||card,pinned=latest.settings.pin_order!=null;await api(settingsPath,{symbol:s.symbol,pin_order:pinned?null:0},'PUT');latest.settings.pin_order=pinned?null:0;pin.textContent=pinned?'置顶':'取消置顶';if(!pinned)$('advisory-cards').prepend(node);await refresh();});pin.className='pin-stock';pin.title='将股票放在列表前面；不会改变跟踪或AI';header.append(pin);node.append(header);
    const liveHealth=document.createElement('p');liveHealth.className='live-health';liveHealth.textContent=`实时数据 ${label(fresh.status)} · 实时监听 ${label(state.listener_state||state.watcher)} · AI ${label(health.ai?.state||'IDLE')} · 当前 ${s.price??'暂无'}`;node.append(liveHealth);
    const checks=card.health?.analysis_status?.eligibility?.evidence_checks||[];if(checks.some(q=>q.status!=='SUFFICIENT')){const detail=document.createElement('details');detail.append(text('summary','自动分析证据检查'));for(const q of checks.filter(q=>q.status!=='SUFFICIENT'))detail.append(text('p',`${q.event_type||'事件'}：${(q.missing||[]).join('、')}`));node.append(detail);}
    const sync=card.sync||{},syncState=sync.status==='SYNCED'?'已同步':sync.status==='PENDING'?'正在同步':sync.status==='LAGGING'?'同步延迟（'+sync.lag_seconds+'秒）':['CLOCK_SKEW','SOURCE_ERROR','ERROR'].includes(sync.status)?'同步异常':'未同步';
    node.append(text('p','数据同步：'+syncState,'sync-summary'));
    const notes=text('div','','source-notes');node.append(notes);
    if(health.previous_eligibility?.eligible===false)notes.append(text('p','历史AI意见保留；其来源或时间范围不符合当前原生分析条件，不作为下一轮上下文。','warning'));
    if(s.observation_status==='NOT_EXPORTED')notes.append(text('p','当前尚无可信观察数据，请检查行情服务的采集状态。','warning'));
    node.append(text('p',s.lifecycle==='ACTIVE'?'正在跟踪':s.lifecycle==='TRACKED'?'已发现当前跟踪；源未导出启停状态':s.lifecycle==='HISTORICAL'?'历史跟踪':'已停止跟踪','lifecycle-summary'));
    const eventBox=document.createElement('section');eventBox.className='live-events';eventBox.append(text('h4','实时事件'));
    const eventNode=e=>{const row=text('p',`${fmt(e.event_time||e.timestamp)} · ${e.summary||e.label||e.event_type||e.type} · ${e.price??'—'} `),severity=e.severity||e.level||'INFO';row.append(text('span',({INFO:'普通记录',WATCH:'值得关注',NOTICE:'值得关注',IMPORTANT:'重点关注',CRITICAL:'⚠ 严重警示'})[severity]||severity,'event-severity event-'+severity.toLowerCase()));if(card.latest?.tracking_session_id===s.tracking_session_id&&e.event_seq!=null&&e.event_seq<=(card.latest.input_event_seq_to||0))row.append(text('span','已分析','event-advised'));return row;};
    eventBox.append(...(card.events||[]).slice(-1).reverse().map(eventNode));
    if(card.event_summary?.text)eventBox.append(text('p',card.event_summary.text,'event-summary'));
    if((card.events||[]).length>1){const all=document.createElement('details');all.append(text('summary','查看全部事件'),...(card.events||[]).slice().reverse().map(eventNode));eventBox.append(all);}node.append(eventBox);

    if(fresh.status==='STALE')notes.append(text('p','数据已延迟，自动AI已暂停。手动分析会明确标记陈旧数据。','warning'));
    const controls=document.createElement('div');controls.className='toolbar advisory-controls';const provider=document.createElement('select'),model=document.createElement('select'),reasoning=document.createElement('select'),auto=document.createElement('select'),message=text('span','','advisory-message');options(reasoning,[['none','关闭额外思考'],['low','低（推荐）'],['high','高'],['max','最高']].map(x=>({value:x[0],label:x[1]})),setting.reasoning_effort);options(auto,[['OFF','自动关闭'],['IMPORTANT_ONLY','仅重要事件'],['ALL_EVENTS','所有已选事件']].map(x=>({value:x[0],label:x[1]})),setting.auto_ai_mode);configureModel(provider,model,setting,reasoning);
    const save=button('保存个股设置',async()=>{try{await api(settingsPath,{symbol:s.symbol,provider:provider.value,model:model.value,reasoning_effort:reasoning.value,auto_ai_mode:auto.value},'PUT');message.textContent='设置已保存';await refresh();}catch(e){message.textContent=chinese(e.message);}});
    const analyze=button('立即分析',async()=>{analyze.disabled=true;message.textContent='AI正在分析冻结窗口…';try{const result=await api(analyzePath,{mode:'NORMAL'});if(['NO_NEW_DATA','STALE_SOURCE_CONFIRM_REQUIRED'].includes(result.status)){message.textContent=chinese(result.message);force.textContent=result.status==='STALE_SOURCE_CONFIRM_REQUIRED'?'确认按陈旧数据分析':'仍然重新分析';force.hidden=false;return;}message.textContent=result.status==='PENDING_AGGREGATION'?'该股票正在分析；新市场事实会继续同步。':'分析完成';await refresh();}catch(e){if(e.code==='NO_NEW_ADVISORY_DATA'||e.code==='STALE_SOURCE_CONFIRM_REQUIRED'){message.textContent=chinese(e.message);force.hidden=false;force.textContent=e.code==='STALE_SOURCE_CONFIRM_REQUIRED'?'确认按陈旧数据分析':'仍然重新分析';}else message.textContent=chinese(e.message);}finally{analyze.disabled=false;}});
    const force=button('仍然重新分析',async()=>{force.disabled=true;message.textContent='正在按明确请求重新分析…';try{await api(analyzePath,{mode:'FORCE_REANALYSIS'});message.textContent='本次重分析请求已处理';force.hidden=true;await refresh();}catch(e){message.textContent=chinese(e.message);}finally{force.disabled=false;}});force.hidden=true;force.className='force-reanalysis';
    const portfolio=card.health?.portfolio||{},position=portfolio.position||{},accountKnown=Boolean(portfolio.account_id)&&!['ERROR','NOT_INITIALIZED'].includes(portfolio.status),positionWeight=portfolio.current_position_weight??position.weight;const portfolioBox=text('section','');portfolioBox.className='live-portfolio';portfolioBox.append(text('h4','当前影子账户'),text('p',!accountKnown&&portfolio.status!=='NOT_INITIALIZED'?'账户暂不可读，市场事实继续显示，执行暂停':portfolio.status==='NOT_INITIALIZED'?'未选择执行账户':`仓位 ${(positionWeight==null?'未知':(positionWeight*100).toFixed(2))}% · 数量 ${position.qty||0} · 可卖 ${position.available_qty||0} · T+1 ${position.locked_qty||0} · 成本 ${position.avg_cost?.toFixed(2)||'—'} · 浮盈亏 ${position.unrealized_pnl?.toFixed(2)||'—'}`),text('p',Object.entries(position.ownership||{}).map(([k,v])=>`${k==='MANUAL_PROTECTED'?'手工保护':k==='AI_MANAGED'?'AI管理':k} ${v}`).join(' · ')));
    if(portfolio.new_risk_paused)portfolioBox.append(text('p','已暂停新增风险：不建仓、不加仓；减仓仍需通过原有检查。'));
    if(portfolio.ai_execution_paused)portfolioBox.append(text('p','账户状态异常，自动模拟执行已暂停。'));
    const modeText={OFF:'关闭',IMPORTANT_ONLY:'仅重要事件',ALL_EVENTS:'所有已选事件',ADVISORY_ONLY:'只给建议',AUTO_SHADOW_EXECUTION:'自动影子交易'},actionLabel={OPEN:'建仓',ADD:'加仓',REDUCE:'减仓',EXIT:'清仓',HOLD:'持有',NONE:'不行动'},executionLabel={BLOCKED:'暂未执行',NOT_RECORDED:'暂无执行记录',EXECUTED:'已执行',PARTIALLY_EXECUTED:'部分执行',DEFERRED:'暂缓',POLICY_REJECTED:'未执行',FAILED:'未执行',WAITING_HUMAN_CONFIRMATION:'等待确认',OFF:'关闭',NOT_INITIALIZED:'未选择执行账户'},reasonLabel={PERSISTENCE_RECOVERY_REQUIRES_REVIEW:'已恢复保存结果，未补发模拟交易，请按原人工流程核对',MARKET_EVIDENCE_INCOMPLETE:'市场证据不完整',NEEDS_SIZING:'尚未确定目标仓位',SUPERSEDED_ANALYSIS:'意见已被更新的请求或判断替代，请重新分析',ACCOUNT_CONTEXT_CHANGED:'账户已变化，请按最新持仓重新分析',EXECUTION_NOT_RECORDED:'请核对账户；不会自动重放旧计划',T1_LOCK:'T+1锁定，等待可卖',MANUAL_PROTECTED:'手工保护仓，AI不可自动卖出',POSITION_LIMIT:'达到单票仓位上限',MAX_TOTAL_EXPOSURE:'达到总仓位上限',MAX_NEW_EXPOSURE_PER_DAY:'达到当日新增仓位上限',MINIMUM_CASH_RESERVE:'须保留最低现金',STALE_QUOTE:'报价已过期',STALE_PORTFOLIO_QUOTE:'持仓报价已过期',QUOTE_UNAVAILABLE:'暂无可用报价',ACCOUNT_EXECUTION_ERROR:'账户执行异常',TARGET_ALREADY_REACHED:'已达到目标仓位',RECONCILIATION_REQUIRED:'账户需要核对',NO_EXECUTION_ACTION:'无需交易',READY_FOR_REEVALUATION:'需重新评估',ACCOUNT_GENERATION_CHANGED:'账户版本已切换',FUTURE_QUOTE:'报价晚于当前时间'};
    portfolioBox.append(text('p',`AI自动分析：${modeText[setting.auto_ai_mode]} · 账户执行：${modeText[portfolio.policy?.ai_execution_mode||portfolio.ai_execution_mode]||'未选择执行账户'}`));
  Object.assign(reasonLabel,{ACCOUNT_BINDING_CHANGED:'账户已切换，本轮未执行',ACCOUNT_STATE_CHANGED:'账户状态已变化，本轮未执行',ACCOUNT_CONTEXT_CHANGED:'账户状态已变化，本轮未执行',NEW_RISK_PAUSED:'已暂停新增风险，未加仓',NO_EXECUTION_ACCOUNT:'未选择执行账户',ACTION_POSITION_CONFLICT:'操作与当前持仓不符',ACTION_TARGET_CONFLICT:'操作与目标仓位方向不符'});
    const lastAction=portfolio.recent_actions?.at(-1);if(lastAction){const weight=lastAction.target_weight==null?'':(lastAction.target_weight*100).toFixed(1)+'%';portfolioBox.append(text('p',`${lastAction.source==='LIVE_MANUAL'?'用户手动':lastAction.source==='LIVE_AI_AUTO'?'自动模拟':'已确认模拟'}${actionLabel[lastAction.portfolio_action]||''} ${weight} · ${executionLabel[lastAction.status]||'已记录'} · ${reasonLabel[lastAction.reason]||''} · 执行 ${lastAction.executed_qty} / 阻止 ${lastAction.blocked_qty} · 成交价 ${lastAction.execution_price??'—'} · ${fmt(lastAction.market_time)}`));}
    const outcome=health.portfolio_execution;if(outcome)portfolioBox.append(text('p',`本条AI模拟交易：${executionLabel[outcome.status]||'已记录'} · ${reasonLabel[outcome.reason]||''}`));
    const plan=card.latest?.portfolio_plan;if(plan){portfolioBox.append(text('p',`当前组合计划 ${actionLabel[plan.portfolio_action]||plan.portfolio_action} · 目标 ${plan.target_weight==null?'尚未确定目标仓位':(plan.target_weight*100).toFixed(1)+'%'} · ${plan.reason}`));if(portfolio.account_id&&portfolio.policy?.ai_execution_mode==='ADVISORY_ONLY'&&['OPEN','ADD','REDUCE','EXIT'].includes(plan.portfolio_action))portfolioBox.append(button('确认本条 AI 模拟计划',async()=>{if(!confirm('确认此条模拟计划？执行仍受账户策略、报价和 T+1 校验。'))return;try{const result=await api(`/api/accounts/${portfolio.account_id}/advisories/${card.latest.advisory_id}/confirm`,{confirmed:true});message.textContent=`${result.status} · ${result.reason||''} · 执行 ${result.executed_qty||0}`;await refresh();}catch(e){message.textContent=chinese(e.message);}}));}
    const accountLink=text('a','管理组合账户');accountLink.href=portfolio.account_id?'/account?account_id='+portfolio.account_id:'/account';accountLink.href+=(accountLink.href.includes('?')?'&':'?')+'from=live';portfolioBox.append(accountLink);node.append(portfolioBox);
    const aiDetails=document.createElement('details');aiDetails.append(text('summary','个股AI设置'),text('p',setting.model_configuration_origin==='OVERRIDE'?'此股使用独立模型配置':'此股跟随 System 默认模型'),button('模型跟随默认',async()=>{await api(settingsPath,{symbol:s.symbol,follow_default:true},'PUT');await refresh();}),text('label','AI服务 '),provider,text('label','模型 '),model,text('label','思考强度 '),reasoning);
    auto.setAttribute('aria-label','AI自动分析');auto.onchange=async()=>{await api(settingsPath,{symbol:s.symbol,auto_ai_mode:auto.value},'PUT');await refresh();};
    const triggerSettings=document.createElement('details');triggerSettings.append(text('summary','自动分析事件'),text('p',`模式来源：${setting.configuration_origin?.mode==='GLOBAL'?'全局默认':'本股覆盖'}；类型来源：${setting.configuration_origin?.types==='STOCK'?'本股覆盖':'继承默认'}。模式控制严重级别，勾选控制类型；所有已选事件包括普通记录，空列表不触发。`));
    const persistTypes=async()=>{const types=[...triggerSettings.querySelectorAll('input:checked')].map(x=>x.dataset.eventType);await api(`/api/live/${s.symbol}/preferences`,{auto_event_types:types},'PUT');};
    triggerSettings.append(button('全选原生事件',async()=>{for(const c of triggerSettings.querySelectorAll('input[data-event-type]'))if(!c.dataset.eventType.startsWith('LIVE_'))c.checked=true;await persistTypes();await refresh();}),button('清空原生事件',async()=>{for(const c of triggerSettings.querySelectorAll('input[data-event-type]'))if(!c.dataset.eventType.startsWith('LIVE_'))c.checked=false;await persistTypes();await refresh();}),button('继承全局范围',async()=>{await api(`/api/live/${s.symbol}/preferences`,{auto_event_types:null},'PUT');await refresh();}));
    for(const [type,name] of Object.entries(card.event_types||{})){const lab=document.createElement('label'),check=document.createElement('input');check.type='checkbox';check.checked=setting.auto_event_types==null?!type.startsWith('LIVE_'):setting.auto_event_types.includes(type);check.dataset.eventType=type;lab.append(check,text('span',name));triggerSettings.append(lab);check.onchange=async()=>{await persistTypes();};}
    if(setting.provider_status?.status==='ERROR'){analyze.disabled=true;force.disabled=true;message.textContent='AI服务不可用，请检查AI配置；市场事实继续同步。';}
    controls.append(text('label','AI自动分析 '),auto,button('继承全局模式',async()=>{await api(settingsPath,{symbol:s.symbol,auto_ai_mode:null},'PUT');await refresh();}),analyze,force,message,text('span',`${setting.model} / ${label(setting.reasoning_effort)}`),triggerSettings,aiDetails,save);node.insertBefore(controls,eventBox);node.append(compactUpdate?text('section','','opinion-brief'):opinionView(card.latest));
    const sessionQuery='tracking_session_id='+encodeURIComponent(s.tracking_session_id);
    node.append(savedHistory('查看博弈时间轴',timelinePath+(timelinePath.includes('?')?'&':'?')+sessionQuery,'timeline',timelineNode,'advisory-timeline'));
    if(true)node.append(savedHistory('查看历史AI意见',`/api/live/${s.symbol}/advisory/history?${sessionQuery}`,'opinions',value=>{
      const row=text('details','','history-opinion');row.append(text('summary',`${fmt(value.generated_at)} · ${actionText[value.action]||label(value.action)}`));
      row.addEventListener('toggle',()=>{if(row.open&&!row.querySelector('.opinion-brief'))row.append(opinionView(value));});return row;
    },'advisory-history'));
    const body=text('div','','stock-body');body.id='stock-body-'+s.symbol;
    for(const child of [...node.children])if(child!==header)body.append(child);
    const collapsed=setting.collapsed!==false;body.hidden=collapsed;
    const toggle=button(collapsed?'展开':'收起',()=>foldStock(s.symbol,!node.querySelector('.stock-body').hidden),'stock-toggle');
    toggle.setAttribute('aria-expanded',String(!collapsed));toggle.setAttribute('aria-label',collapsed?'展开':'收起');toggle.setAttribute('aria-controls',body.id);if(true)header.prepend(toggle);
    node._displayedCard=card;node.id='stock-'+s.symbol;node.dataset.collapsed=String(collapsed);
    const unread=card.unread||{},brief=text('div','','stock-summary');
    brief.append(text('strong',s.price==null?'暂无可信现价':`现价 ${s.price}`),timeBadge('当前行情截至',s.price_time),
      text('span',`当前阅读：${card.latest?actionText[card.latest.action]||card.latest.action:'尚无意见'} · 意见截至 ${card.latest?(card.latest.data_through_at?fmt(card.latest.data_through_at):'旧记录未保存'):'—'}`,'viewed-opinion'),
      text('span',`新意见 ${unread.opinions||0} · 判断变化 ${unread.important_changes||0} · 未读事件 ${unread.events||0}`,'unread-badge'),
      text('span',`仓位 ${!accountKnown&&portfolio.status!=='NOT_INITIALIZED'?'暂不可读':portfolio.status==='NOT_INITIALIZED'?'未选择执行账户':(positionWeight==null?'未知':(positionWeight*100).toFixed(1))+'%'}`),analyze,force,message);
    brief.querySelector('.viewed-opinion').dataset.opinionId=card.latest?.advisory_id||'';
    brief.append(analysisState(card));
    if(health.market?.evidence_status)brief.append(text('span',label(health.market.evidence_status)));
    if(true)header.append(button('标为已读',async()=>{try{await acknowledge(node._displayedCard);await refresh();}catch(e){message.textContent=chinese(e.message);}},'mark-read'));
    // Market view, AI plan and actual account outcome remain separate.
    body.insertBefore(body.querySelector('.opinion-brief')||body.querySelector('.ai-review'),body.firstChild);
    node.append(brief,body);if(health.previous_eligibility?.eligible===false){const notes=body.querySelector('.source-notes');if(notes)body.prepend(notes);}for(const d of node.querySelectorAll('details')){const key='live-details:'+location.origin+':'+'REAL'+':'+(state?.source||'')+':'+s.tracking_session_id+':'+d.querySelector('summary')?.textContent;try{d.open=localStorage.getItem(key)==='true';}catch{}d.addEventListener('toggle',()=>{try{localStorage.setItem(key,String(d.open));}catch{}});}return node;}
  function renderGlobalSettings(settings){if(globalSettingsDirty||$('advisory-global-settings').contains(document.activeElement))return;const global=settings.global;configureModel($('advisory-global-provider'),$('advisory-global-model'),global,$('advisory-global-reasoning'));$('advisory-global-reasoning').value=global.reasoning_effort;$('advisory-global-auto').value=global.auto_ai_mode;$('advisory-debounce').value=global.debounce_seconds;$('fresh-seconds').value=global.fresh_seconds;$('delayed-seconds').value=global.delayed_seconds;}
  function renderSettings(data){
    if(data.advisory_settings)renderGlobalSettings(data.advisory_settings);
    const filters=$('observed-stocks');
    for(const card of data.advisory_cards){const symbol=card.session.symbol;let lab=[...filters.children].find(n=>n.dataset.symbol===symbol);
      if(!lab){lab=text('label','');lab.dataset.symbol=symbol;const check=document.createElement('input');check.type='checkbox';check.dataset.symbol=symbol;check.onchange=async()=>{try{await api(`/api/live/${symbol}/preferences`,{visible:check.checked},'PUT');await refresh();}catch(e){$('live-status').textContent=chinese(e.message);}};lab.append(check,text('span',''));filters.append(lab);}
      const check=lab.querySelector('input');if(document.activeElement!==check)check.checked=card.settings.visible!==false;lab.querySelector('span').textContent=`${card.session.name} ${symbol.replace(/^[a-z]+/,'')}`;
    }
    for(const lab of [...filters.children])if(!data.advisory_cards.some(c=>c.session.symbol===lab.dataset.symbol))lab.remove();
    const container=$('advisory-cards'),oldCards=new Map([...container.children].map(n=>[n.dataset.symbol,n]));
    const visible=data.advisory_cards.filter(c=>c.settings.visible!==false);
    for(const symbol of localFolds.keys())if(!data.advisory_cards.some(c=>c.session.symbol===symbol))localFolds.delete(symbol);
    for(const c of visible){const symbol=c.session.symbol;if(localFolds.has(symbol))c.settings.collapsed=localFolds.get(symbol);
      const old=oldCards.get(symbol),identity=[data.source||'',data.source_generation||'',c.session.tracking_session_id].join('|');
      if(old&&old.dataset.identity===identity){patchCard(old,c);continue;}
      const node=advisoryCard(c);node.dataset.identity=identity;if(old)old.replaceWith(node);else container.append(node);
    }
    for(const child of [...container.children])if(!visible.some(c=>c.session.symbol===child.dataset.symbol))child.remove();
    const changed=visible.filter(c=>(c.unread?.opinions||0)>0),important=visible.filter(c=>(c.unread?.important_changes||0)>0);
    const summary=$('reading-summary');let note=summary.querySelector('span');if(!note){note=text('span','');summary.prepend(note);}note.textContent=`自上次查看：${changed.length}只股票有新意见，${important.length}只判断发生变化。`;for(const c of changed){if(![...summary.querySelectorAll('button')].some(b=>b.dataset.symbol===c.session.symbol)){const b=button(c.session.name,()=>{const n=$('stock-'+c.session.symbol);n?.scrollIntoView({block:'center',behavior:'smooth'});n?.querySelector('.stock-toggle')?.focus({preventScroll:true});});b.dataset.symbol=c.session.symbol;summary.append(b);}}for(const b of summary.querySelectorAll('button'))if(!changed.some(c=>c.session.symbol===b.dataset.symbol))b.remove();
  }

  const portfolioUpdates=new BroadcastChannel('tradinglab.portfolio.changed');portfolioUpdates.onmessage=()=>refresh().catch(()=>{});
  const displayRefresh=new TradingLabDisplayRefresh(refreshNow,{period:2000,onPause:()=>{refreshRevision++;},onError:e=>$('live-status').textContent=chinese(e.message)});
  window.addEventListener('focus',()=>refresh());
  function refresh(){return displayRefresh.refresh();}
  async function refreshNow(){
    const revision=++refreshRevision;
    if(!versionChecked){versionChecked=true;api('/api/live/runtime-version').then(version=>{if(version.build_id!=='__LIVE_BUILD_ID__')$('live-status').textContent='页面与服务版本不一致，请重新加载页面。';}).catch(()=>{versionChecked=false;});}

    let settingsResult={status:'pending'};
    // Stocks already carry the complete catalog. Revalidate separately at startup,
    // after commands and every 30s for other tabs / provider configuration changes.
    if(!settingsFlight&&Date.now()>=nextSettingsAt){
      settingsFlight=api('/api/live/advisory/settings').then(value=>{settingsFailures=0;nextSettingsAt=Date.now()+30000;settingsResult={status:'fulfilled',value};if(revision===refreshRevision&&state){state.advisory_settings=value;renderGlobalSettings(value);}}).catch(reason=>{settingsFailures=Math.min(settingsFailures+1,4);nextSettingsAt=Date.now()+Math.min(30000,2000*2**settingsFailures);settingsResult={status:'rejected',reason};if(revision===refreshRevision)$('live-status').textContent+=' · AI配置读取失败，保留已有设置';}).finally(()=>{settingsFlight=null;});
    }
    const [factsResult]=await Promise.allSettled([api('/api/live/stocks?view=display&opinions='+encodeURIComponent((state?.advisory_cards||[]).map(c=>c.latest?.advisory_id||'').join(',')))]);
    if(revision!==refreshRevision)return;
    if(settingsResult.status==='fulfilled'){
      state={...(state||{}),advisory_settings:settingsResult.value};renderGlobalSettings(settingsResult.value);
    }
    if(factsResult.status==='rejected'){
      $('live-status').textContent='实时数据读取失败：'+factsResult.reason.message;
      if(settingsResult.status==='rejected')$('live-status').textContent+='；AI配置读取失败：'+settingsResult.reason.message;
      return false;
    }
    const data=factsResult.value;for(const card of data.advisory_cards||[])if(card.latest_unchanged_id){const previous=state?.advisory_cards?.find(c=>c.session.tracking_session_id===card.session.tracking_session_id&&c.latest?.advisory_id===card.latest_unchanged_id);if(previous)card.latest=previous.latest;}
    if(data.status==='INITIAL_LOADING'){$('live-status').textContent=data.message;return;}
    if((data.fact_error||data.source_status?.listener_state==='SOURCE_ERROR')&&state?.advisory_cards?.length){const badge=document.querySelector('.title-row .status');if(badge)badge.textContent='数据源异常';$('live-status').textContent='源读取异常，保留上次成功内容（非当前数据）：'+(data.fact_error?.message||data.source_status.error||'原生文件校验失败');return;}
    state=data;
    if(settingsResult.status==='fulfilled')data.advisory_settings=settingsResult.value;
    const sync=data.source_status||{},provider=data.advisory_settings.provider_status||{};
    const badge=document.querySelector('.title-row .status');if(badge)badge.textContent=data.read_model?.refresh_state==='REFRESH_FAILED'?'数据源读取异常':data.read_model?.refresh_state&&data.read_model.refresh_state!=='CURRENT'?'正在验证连接':data.connection?.status==='CONNECTED'?label(sync.listener_state||data.listener_state||'CONNECTED'):'数据源未连接';
    $('live-status').textContent=`${data.source==='TEST'?'测试数据（TEST）':'正式数据'} · 实时监听 ${label(data.listener_state)}`;
    if(data.fact_error)$('live-status').textContent+=' · '+data.fact_error.message;
    if(data.read_model)$('live-status').textContent+=` · 上次整理 ${fmt(data.read_model.collected_at)}${data.read_model.refresh_state!=='CURRENT'?' · 后台刷新中／保留上次成功内容':''}`;
    if(settingsResult.status==='rejected')$('live-status').textContent+=' · AI配置读取失败：'+settingsResult.reason.message;
    const sampling={UNKNOWN:'未知（源未导出启停状态）',RUNNING:'运行中',STOPPED:'已停止'};
    $('live-workspace').textContent=`数据源：${data.source_owner==='MARKET_DATA_AGENT'?'Market Data Agent':'隔离历史事实'} ${data.connection.status==='CONNECTED'?'已连接':'连接需检查'} · 当前跟踪 ${data.active_sessions} · 源快速采样 ${sampling[sync.sampling_state]||'未知'} · AI ${data.ai_running}分析中 / ${data.ai_queued}排队`;
    if(data.advisory_cards.length&&data.advisory_cards.every(c=>c.session.price==null))$('live-workspace').textContent+=' · 暂无可信实时行情，请检查 Market Data Agent 的连接和采集状态。';
    renderSettings(data);try{sessionStorage.setItem('live-success:'+location.origin,JSON.stringify(data));}catch{}
    const hiddenAI=data.advisory_cards.filter(c=>c.settings.visible===false&&c.settings.auto_ai_mode!=='OFF');if(hiddenAI.length)$('live-status').textContent+=' · 隐藏股票仍启用AI：'+hiddenAI.map(c=>c.session.name).join('、');
  }
  for(const event of ['input','change'])$('advisory-global-settings').addEventListener(event,()=>{globalSettingsDirty=true;});
  $('advisory-global-settings').onsubmit=async e=>{e.preventDefault();try{const path='/api/live/advisory/settings';await api(path,{auto_ai_mode:$('advisory-global-auto').value,debounce_seconds:Number($('advisory-debounce').value),fresh_seconds:Number($('fresh-seconds').value),delayed_seconds:Number($('delayed-seconds').value)},'PUT');globalSettingsDirty=false;await refresh();$('live-status').textContent='全局 AI 设置已保存';}catch(error){$('live-status').textContent=chinese(error.message);}};
  $('watcher-start').onclick=()=>act('/api/live/listener/start');$('watcher-stop').onclick=()=>act('/api/live/listener/stop');$('live-refresh').onclick=()=>refresh().catch(e=>$('live-status').textContent=chinese(e.message));
  for(const [id,collapsed] of [['collapse-all',true],['expand-all',false]])$(id).onclick=async()=>{for(const card of state?.advisory_cards||[])if(card.settings.visible!==false)foldStock(card.session.symbol,collapsed);};
  api('/api/live/view-context').then(ctx=>{if(state)return;try{const saved=JSON.parse(sessionStorage.getItem('live-success:'+location.origin));if(saved&&saved.source===ctx.source&&(saved.source_generation||'')===(ctx.source_generation||'')&&JSON.stringify(saved.advisory_cards.map(c=>c.session.tracking_session_id))===JSON.stringify(ctx.sessions)){state=saved;renderSettings(saved);$('live-status').textContent='上次成功内容 · '+fmt(saved.read_model?.collected_at)+' · 正在更新';}}catch{}}).catch(()=>{});
  refresh();window.addEventListener('pagehide',event=>{if(!event.persisted)portfolioUpdates.close();});
})();
