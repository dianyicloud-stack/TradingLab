// Application adapter around unchanged native JavaScript functions. No DOM.
import {createCore} from './native_core.mjs';
import {createHash} from 'node:crypto';
export const hash=value=>createHash('sha256').update(JSON.stringify(value)).digest('hex');
const RealDate=globalThis.Date;
export function createRuntime(saved={}, options={}) {
  let clock=options.now||null;const archived=saved.archived_sessions||[];const testBaselines=new Map(),testDailyBaselines=new Map();
  class ClockDate extends RealDate {constructor(...args){super(...(args.length?args:[clock||RealDate.now()]));}static now(){return clock?new RealDate(clock).getTime():RealDate.now();}}
  const ports={Date:ClockDate, state:saved.state||{profiles:{},boardProfiles:{}},
    tracker:{store:saved.store||{watchlist:[],sessions:{},session_seq_by_symbol:{},volumeRatioDays:20}},
    runtimeState:saved.runtimeState||{},runtimeCache:{},runtimeMonitor:{running:true,generation:1,stats:{state_write_count:0}},
    eventEngine:{events:[],analysisState:{},decisionCheckpoint:{},handoffHistory:[],...saved.eventEngine,eventKeys:new Set(),persistedEventKeys:new Set()},
    storage:{getItem:()=>null,setItem:()=>{}},...options.ports};
  for(const name of ['dailyCache','volumeHistoryCache','boardDailyCache','boardMinuteCache','boardBreadthCache','boardHealth','breadthHealth','stockTradeCache','currentQuoteCache','csvHandles','csvWriteQueues','csvRuntimeStatus'])ports.tracker[name]=new Map();
  ports.tracker.copySelection=new Set();ports.tracker.runningSymbols=[];
  for(const name of ['stock','industry','indexes','breadth','profiles','boardProfiles'])ports.runtimeCache[name]=new Map();
  for(const name of ['saveTrackerStore','saveEventEngineStore','saveProfiles','saveBoardProfiles'])ports[name]=()=>{}; // Owner commits the returned state transactionally.
  for(const name of ['renderTracker','renderEventCenter','renderRealtimeMonitor','refreshDecisionAckStatus','renderDecisionAckResult','closeCheckpointModal','showToast','setRuntimeFileStatus','setEventFileStatus'])ports[name]=()=>{};
  ports.deleteCsvHandle=async()=>{};ports.clearPendingAckUi=()=>{ports.eventEngine.pendingAckPlan=null;};
  ports.withRuntimeStateLock=async task=>task();ports.navigator={locks:{owner:'AGENT_OS_LEASE'}};
  const flights=new Map(),backoff=new Map();
  async function fetchText(url,timeout=10000){
    if(!options.network)throw new Error('MARKET_NETWORK_NOT_AUTHORIZED');
    const u=new URL(url);
    if(u.protocol!=='https:'||!['sina.cn','sina.com.cn','eastmoney.com'].some(x=>u.hostname===x||u.hostname.endsWith('.'+x)))throw new Error('MARKET_HOST_REJECTED');
    const key=u.origin+u.pathname;
    if((backoff.get(u.origin)||0)>RealDate.now())throw new Error('MARKET_SOURCE_BACKOFF');
    if(flights.has(url))return flights.get(url);
    const pending=(async()=>{try{
      const response=await fetch(url,{signal:AbortSignal.timeout(Math.min(timeout,22000)),redirect:'error'});
      if(!response.ok)throw new Error('MARKET_HTTP_'+response.status);
      const bytes=await response.arrayBuffer();if(bytes.byteLength>8*1024*1024)throw new Error('MARKET_RESPONSE_TOO_LARGE');
      return new TextDecoder(/gb/i.test(response.headers.get('content-type')||'')?'gb18030':'utf-8').decode(bytes);
    }catch(e){backoff.set(u.origin,RealDate.now()+15000);throw e;}finally{flights.delete(url);}})();flights.set(url,pending);return pending;
  }
  // Parse data, never execute remote JavaScript. Unsupported provider syntax fails closed.
  function parseEnvelope(body,variable,callback=false){
    const escaped=variable.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
    const expression=callback?new RegExp('^\\s*'+escaped+'\\s*\\(([\\s\\S]*)\\)\\s*;?\\s*$'):new RegExp('^(?:\\s*/\\*[\\s\\S]*?\\*/)*\\s*(?:var\\s+)?'+escaped+'\\s*=\\s*([\\s\\S]*?)\\s*;?\\s*$');
    const match=body.match(expression);if(!match)throw new Error('MARKET_JSONP_ENVELOPE_INVALID');
    let data=match[1].trim();if(data.startsWith('(')&&data.endsWith(')'))data=data.slice(1,-1).trim();
    return JSON.parse(data);
  }
  ports.loadJsonpVariable=async(url,name,timeout)=>parseEnvelope(await fetchText(url,timeout),name);
  ports.loadJsonpCallback=async(endpoint,params,key='cb',timeout)=>{const name='tl_agent_callback';return parseEnvelope(await fetchText(endpoint+'?'+new URLSearchParams({...params,[key]:name}),timeout),name,true);};
  if(options.transport)Object.assign(ports,options.transport);
  const core=createCore(ports);
  ports.eventEngine.analysisState=core.normalizeAnalysisState(ports.eventEngine.analysisState);
  ports.eventEngine.decisionCheckpoint=core.normalizeDecisionCheckpoint(ports.eventEngine.decisionCheckpoint);
  ports.eventEngine.eventKeys=new Set(ports.eventEngine.events.map(e=>e.event_key));
  function state(){const e=ports.eventEngine;return JSON.parse(JSON.stringify({store:ports.tracker.store,state:ports.state,runtimeState:ports.runtimeState,
    archived_sessions:archived,event_statuses:Object.fromEntries(e.events.map(v=>[v.event_id,core.eventActionability(v)])),eventEngine:{events:e.events,analysisState:e.analysisState,decisionCheckpoint:e.decisionCheckpoint,handoffHistory:e.handoffHistory,activeHandoff:e.activeHandoff}}));}
  function setClock(now){if(now&&!Number.isFinite(new RealDate(now).getTime()))throw new Error('INVALID_CLOCK');clock=now||null;}
  function rollover(){const today=core.chinaToday();for(const item of ports.tracker.store.watchlist){if(item.lifecycle_status==='DROPPED')continue;core.ensureTrackerSession(item.symbol,item);}core.ensureAllTrackingSessionCursors();return today;}
  function command(value){
    setClock(value.now);
    // Identity allocation only: leave all native market/ACK calculations unchanged.
    if(value.action==='RESERVE_SESSIONS'){
      if(!Array.isArray(value.reserved_session_ids)||value.reserved_session_ids.length>5000)throw Error('SESSION_RESERVATIONS_INVALID');
      const floors={};
      for(const id of value.reserved_session_ids){
        const m=/^TS-(\d{4})(\d{2})(\d{2})-((?:sh|sz|bj)\d{6})-(\d+)$/.exec(id);
        if(!m)throw Error('SESSION_RESERVATIONS_INVALID');
        if(ports.tracker.store.sessions[id]||archived.some(s=>s.tracking_session_id===id))throw Error('SESSION_IDENTITY_COLLISION');
        const key=`${m[1]}-${m[2]}-${m[3]}|${m[4]}`;
        floors[key]=Math.max(floors[key]||0,Number(m[5]));
      }
      const counters=ports.tracker.store.session_seq_by_symbol||={};
      for(const [key,floor] of Object.entries(floors))counters[key]=Math.max(counters[key]||0,floor);
      return state();
    }
    if(value.action==='PARAMETERS'){
      if(![10,20].includes(value.volume_ratio_days))throw Error('VOLUME_RATIO_DAYS_INVALID');
      ports.tracker.store.volumeRatioDays=value.volume_ratio_days;return state();
    }
    let symbol=core.normalizeStockSymbol(value.symbol);
    let item=ports.tracker.store.watchlist.find(x=>x.symbol===symbol);
    if(value.action==='ADD'){
      if(item&&item.lifecycle_status!=='DROPPED')throw new Error('TRACKING_ALREADY_EXISTS');
      if(ports.tracker.store.watchlist.filter(x=>x.lifecycle_status!=='DROPPED').length>=5)throw new Error('MAX_TRACK_STOCKS');
      if(!value.board?.code||!value.board?.name||!value.name)throw new Error('NAME_AND_BOARD_REQUIRED');
      const next={id:core.createId(),symbol,boardCode:value.board.code,lifecycle_status:'ACTIVE',aiSelected:true};
      ports.tracker.store.watchlist=ports.tracker.store.watchlist.filter(x=>x.symbol!==symbol);ports.tracker.store.watchlist.push(next);item=next;
      ports.state.boardProfiles[symbol]={name:value.name,boards:[value.board],cachedDate:core.chinaToday()};
      core.assignTrackingSessionToItem(item,symbol);const session=core.ensureTrackerSession(symbol,item);session.stockName=value.name;session.selectedBoardCode=value.board.code;session.selectedBoardName=value.board.name;
    }else if(!item)throw new Error('TRACKING_NOT_FOUND');
    else if(value.action==='PAUSE')core.setTrackerLifecycle(item.id,'PAUSED');
    else if(value.action==='RESUME')core.setTrackerLifecycle(item.id,'ACTIVE');
    else if(value.action==='BOARD'){
      if(!value.board?.code||!value.board?.name)throw Error('BOARD_REQUIRED');
      item.boardCode=value.board.code;ports.state.boardProfiles[symbol]={name:value.name||symbol,boards:[value.board],cachedDate:core.chinaToday()};
      const session=ports.tracker.store.sessions[item.tracking_session_id];session.selectedBoardCode=value.board.code;session.selectedBoardName=value.board.name;
    }
    else if(value.action==='STOP'){
      archived.push(JSON.parse(JSON.stringify({...ports.tracker.store.sessions[item.tracking_session_id],lifecycle_status:'DROPPED'})));
      core.dropTrackerStock(item.id,true);return state();
    }
    else throw new Error('TRACKING_COMMAND_INVALID');
    const session=ports.tracker.store.sessions[item.tracking_session_id];session.lifecycle_status=item.lifecycle_status;
    core.ensureAllTrackingSessionCursors();return state();
  }
  async function cycle({now,frames={},market_open=true,immediate_symbol=null}={}){
    setClock(now);rollover();const snapshots=[],errors=[],gaps=[];
    if(!market_open)return {state:state(),snapshots,errors,gaps};
    const items=core.runtimeConfiguredItems(); // Native PAUSED means not selected for formal analysis; collection continues.
    const index=options.network?await core.getRuntimeIndexSnapshot().catch(()=>null):null;
    for(const item of items){
      const frame=frames[item.symbol],session=core.ensureTrackerSession(item.symbol,item);
      if(frame?.dataset?.volumeHistoryBars)testBaselines.set(item.symbol,frame.dataset.volumeHistoryBars);
      if(frame?.dataset?.stockDailyBars)testDailyBaselines.set(item.symbol,frame.dataset.stockDailyBars);
      try{
        ports.runtimeMonitor.testSampleProvider=frame?async()=>frame.fields:null;
        const sample=await core.sampleOneRuntimeStock(item,ports.runtimeMonitor.generation,index);
        if(sample)snapshots.push({tracking_session_id:session.tracking_session_id,session_date:session.date,sample});
        const point=core.currentTrackerPoint();ports.recordedDataset=symbol=>frames[symbol]?.dataset;
        const result=await core.captureOneTracker(item,null,Boolean(frame?.immediate||immediate_symbol===item.symbol));
        for(const row of result.newRows)if(row.source==='auto'&&row.requestedTime!==point)gaps.push({session:session.tracking_session_id,requested_time:row.requestedTime,captured_at:row.capturedAt,kind:'RECOVERED_HISTORICAL_OBSERVATION'});
      }catch(e){errors.push({symbol:item.symbol,code:e.code||'MARKET_SAMPLE_FAILED',message:e.message});}
    }
    core.syncTrackerEventsToLedger();core.ensureAllTrackingSessionCursors();
    return {state:state(),snapshots,errors,gaps,observations:Object.values(ports.tracker.store.sessions).flatMap(s=>core.trackerRowsWithEventDetails(s.rows).map(raw=>({tracking_session_id:s.tracking_session_id,session_date:s.date,symbol:s.symbol,raw})))};
  }
  async function execute(input){
    if(input.op==='maintenance_baselines'){
      setClock(input.now);
      const all=[...Object.values(ports.tracker.store.sessions),...archived];
      const sessions=ports.tracker.store.watchlist.filter(w=>w.lifecycle_status!=='DROPPED').map(w=>{
        const current=ports.tracker.store.sessions[w.tracking_session_id];
        return current?.date===input.day?current:all.find(s=>s.tracking_session_id===input.restore?.session_scope?.[w.symbol])||current;
      }).filter(Boolean),samples={};
      const missing=[],daily_samples={},board_context={};
      if(input.restore?.day===input.day){
        for(const [key,bars] of Object.entries(input.restore.daily_samples||{}))if(key.startsWith(input.day+'|')&&!ports.tracker.dailyCache.has(key))ports.tracker.dailyCache.set(key,Promise.resolve(bars));
        for(const [key,value] of Object.entries(input.restore.board_context||{}))if(key.startsWith(input.day+'|')&&!ports.tracker.boardMinuteCache.has(key))ports.tracker.boardMinuteCache.set(key,value);
      }
      if(!sessions.length)missing.push({code:'NO_TRACKED_SESSION'});
      await Promise.all(sessions.map(async s=>{
        if(s.date!==input.day||!s.rows?.length){missing.push({symbol:s.symbol,code:'CURRENT_DAY_OBSERVATION_MISSING',day:input.day});return;}
        const volumeKey=`${input.day}|${s.symbol}`,dailyKey=`${volumeKey}|daily`,saved=input.restore;
        // Owner has validated persisted certificate identity/date/version before restore.
        if(saved?.day===input.day){
          if(saved.samples?.[s.symbol]?.length&&!ports.tracker.volumeHistoryCache.has(volumeKey))ports.tracker.volumeHistoryCache.set(volumeKey,Promise.resolve(saved.samples[s.symbol]));
          if(saved.daily_samples?.[dailyKey]?.length&&!ports.tracker.dailyCache.has(dailyKey))ports.tracker.dailyCache.set(dailyKey,Promise.resolve(saved.daily_samples[dailyKey]));
        }
        try{
          if(input.prepare&&options.network&&!ports.tracker.volumeHistoryCache.has(volumeKey))await core.getVolumeHistory(s.symbol);
          if(input.prepare&&options.network&&!ports.tracker.dailyCache.has(dailyKey)){
            const bars=await core.getKline(s.symbol,240,40);ports.tracker.dailyCache.set(dailyKey,Promise.resolve(bars));
          }
        }catch(e){missing.push({symbol:s.symbol,code:'NATIVE_BASELINE_FETCH_FAILED'});}
        const bars=await ports.tracker.volumeHistoryCache.get(volumeKey)||testBaselines.get(s.symbol);
        const daily=await ports.tracker.dailyCache.get(dailyKey)||testDailyBaselines.get(s.symbol);
        if(!bars?.length)missing.push({symbol:s.symbol,code:'VOLUME_HISTORY_MISSING',day:input.day,requested_bars:1023});
        else samples[s.symbol]=bars;
        if(!daily?.length)missing.push({symbol:s.symbol,code:'DAILY_HISTORY_MISSING',day:input.day,requested_bars:40});
        else daily_samples[dailyKey]=daily;
      }));
      for(const [key,promise] of ports.tracker.dailyCache)if(key.startsWith(input.day+'|'))daily_samples[key]=await promise;
      for(const [key,value] of ports.tracker.boardMinuteCache)if(key.startsWith(input.day+'|'))board_context[key]=value;
      return {ready:missing.length===0,missing,day:input.day,volume_ratio_days:ports.tracker.store.volumeRatioDays||20,samples,daily_samples,board_context,
        session_scope:Object.fromEntries(sessions.map(s=>[s.symbol,s.tracking_session_id])),
        missing_board_context:Object.keys(board_context).length?[]:['NOT_EXPORTED'],available_at:clock};
    }
    if(input.op==='maintenance_prune'){
      const ids=new Set(input.sessions);for(let i=archived.length-1;i>=0;i--)if(ids.has(archived[i].tracking_session_id))archived.splice(i,1);
      ports.eventEngine.events=ports.eventEngine.events.filter(e=>!ids.has(e.tracking_session_id));
      for(const [k,s] of Object.entries(ports.tracker.store.sessions))if(ids.has(s.tracking_session_id))delete ports.tracker.store.sessions[k];
      if(input.keep_day)for(const name of ['dailyCache','volumeHistoryCache','boardMinuteCache','stockTradeCache'])for(const key of ports.tracker[name].keys()){
        const match=/^(\d{4}-\d{2}-\d{2})\|/.exec(key);if(match&&match[1]<input.keep_day)ports.tracker[name].delete(key);
      }
      return {status:'PRUNED'};
    }
    if(input.op==='state')return state();
    if(input.op==='command')return command(input);
    if(input.op==='cycle')return cycle(input);
    if(input.op==='metadata'){setClock(input.now);const symbol=core.normalizeStockSymbol(input.symbol);return {profile:await core.getStockProfile(symbol),boards:await core.getStockBoards(symbol)};}
    if(input.op==='parity'){setClock(input.now);return core[input.method](...input.args);}
    throw new Error('AGENT_COMMAND_UNKNOWN');
  }
  return {execute,core,ports,setClock,state};
}
