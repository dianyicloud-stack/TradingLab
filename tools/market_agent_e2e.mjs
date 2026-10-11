import fs from 'node:fs';import path from 'node:path';import {createRequire} from 'node:module';import assert from 'node:assert/strict';
const require=createRequire(import.meta.url),{chromium}=require('./dev/browser.cjs');
const [base,out]=process.argv.slice(2),checks={},pageerror=[],console_error=[],timings={};const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const browser=await chromium.launch({headless:true});const context=await browser.newContext({viewport:{width:1440,height:1050}});
context.on('page',p=>{p.on('pageerror',e=>pageerror.push(e.message));p.on('console',e=>{if(e.type()==='error')console_error.push(e.text())});});
const get=async path=>(await context.request.get(base+path)).json();const post=async(path,data,method='POST')=>{const r=await context.request.fetch(base+path,{method,data});assert(r.ok(),await r.text());return r.json();};
const wait=async(fn,label)=>{for(let i=0;i<120;i++){if(await fn())return;await sleep(150);}throw Error('TIMEOUT '+label);};
let ok=false;
try{
 const observation=await context.newPage();await observation.goto(base+'/data-observation');await observation.getByText('跟踪设置',{exact:true}).click();
 for(const [symbol,name]of [['bj920161','测试甲'],['sh688696','测试乙'],['sz300225','测试丙']]){
  await observation.locator('[name=symbol]').fill(symbol);await observation.locator('[name=name]').fill(name);await observation.locator('[name=board_code]').fill('BKTEST');await observation.locator('[name=board_name]').fill('测试行业');
  await observation.getByRole('button',{name:'添加并跟踪'}).click();await wait(async()=>(await get('/api/data-observation/state')).sessions.some(s=>s.symbol===symbol),'add '+symbol);
 }
 checks.tracking_command_api='PASS';await wait(async()=>await observation.locator('#observation-table tr').count()>1,'observation table');
 await wait(async()=>await observation.locator('#amount-chart svg').count()===1,'amount chart');checks.observation_and_chart_same_facts='PASS';
 await observation.locator('[name=name]').fill('编辑中不应被轮询覆盖');await observation.locator('[name=name]').focus();await sleep(2700);assert.equal(await observation.locator('[name=name]').inputValue(),'编辑中不应被轮询覆盖');assert(await observation.locator('[name=name]').evaluate(n=>n===document.activeElement));checks.edit_preserved_by_poll='PASS';
 await observation.screenshot({path:path.join(out,'data-observation.png'),fullPage:true});
 let before=await get('/api/data-observation/state');const identities=before.sessions.map(s=>s.tracking_session_id);await observation.close();assert.equal(context.pages().length,0);await sleep(1800);let after=await get('/api/data-observation/state');
 assert(after.fact_version>before.fact_version);assert(after.facts.filter(f=>f.kind==='SNAPSHOT').length>before.facts.filter(f=>f.kind==='SNAPSHOT').length);assert.deepEqual(after.sessions.map(s=>s.tracking_session_id),identities);checks.separate_agent_continues_without_browser_pages='PASS';
 const live=await context.newPage();let settingsFinished=false;await live.route('**/api/live/advisory/settings',async r=>{if(r.request().method()==='GET'){await sleep(4000);settingsFinished=true;}await r.continue().catch(()=>{});});const start=performance.now();await live.goto(base+'/live');await wait(async()=>await live.locator('.advisory-card').count()===3,'live three cards');timings.first_cards_ms=performance.now()-start;checks.live_auto_discovery='PASS';assert(!settingsFinished,'cards must appear before slow settings');checks.cached_first_screen_independent_of_settings='PASS';
 assert.equal(await live.locator('.stock-body:visible').count(),0);checks.three_collapsed='PASS';
 await live.getByRole('button',{name:'刷新显示',exact:true}).click().catch(()=>live.locator('#live-refresh').click());await sleep(350);assert.deepEqual((await get('/api/data-observation/state')).sessions.map(s=>s.tracking_session_id),identities);checks.refresh_no_session_recreation='PASS';
 await live.click('#watcher-start');await sleep(500);
 const card=live.locator('.advisory-card[data-symbol="bj920161"]');await card.getByRole('button',{name:'立即分析',exact:true}).click();await live.locator('h1').click();
 await wait(async()=>!!(await get('/api/live/bj920161/advisory/latest')).opinion,'manual current snapshot');checks.agent_to_existing_advisory='PASS';
 const evidence=await get('/api/data-observation/state');assert.equal(evidence.facts.filter(f=>f.kind==='ACK_RECEIPT').length,0);assert(Object.values(evidence.event_badges).some(b=>b.advised));assert(Object.values(evidence.event_badges).every(b=>!b.acked));checks.advisory_does_not_ack='PASS';
 await live.click('#expand-all');await wait(async()=>await live.locator('.stock-body:visible').count()===3,'expand all');await card.getByRole('button',{name:'置顶',exact:true}).click();await live.locator('h1').click();await sleep(400);assert.equal((await get('/api/data-observation/state')).sessions.length,3);checks.pin_only_ui='PASS';
 await live.click('#collapse-all');await wait(async()=>await live.locator('.stock-body:visible').count()===0,'collapse all');await live.reload();await wait(async()=>await live.locator('.advisory-card').count()===3,'reload');assert.equal(await live.locator('.stock-body:visible').count(),0);checks.collapse_persists='PASS';
 await live.screenshot({path:path.join(out,'live-three.png'),fullPage:true});await live.setViewportSize({width:390,height:844});assert(await live.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));checks.mobile='PASS';
 const body=await live.locator('#live-center').innerText();assert(!/\bACK\b|\bReceipt\b|\bHandoff\b/.test(body));checks.formal_outside_live='PASS';
 const audit=await context.newPage();await audit.goto(base+'/decisions');assert.equal((await audit.locator('h1').count()),1);checks.formal_audit_accessible='PASS';
 const source=await context.newPage();source.on('dialog',d=>d.accept());await source.goto(base+'/data-observation');await wait(async()=>(await source.locator('#data-status').textContent()).includes('后台运行中'),'source state ready');await source.getByText('正式确认状态与审计',{exact:true}).click();await source.locator('#source-handoff').click();await wait(async()=>{const s=await get('/api/data-observation/state');return s.facts.some(f=>f.kind==='HANDOFF');},'native handoff');
 const facts=await get('/api/data-observation/state'),h=facts.facts.filter(f=>f.kind==='HANDOFF').at(-1).payload.document,s=h.selected_tracking_sessions.find(s=>s.symbol==='bj920161'),c=h.cursor_snapshot[s.tracking_session_id];
 const ack={schema_version:'1.0',ack_type:'DECISION_CONFIRMATION',ack_id:'ACK-TEST-BROWSER',decision_id:'DEC-TEST-BROWSER',job_id:'JOB-TEST-BROWSER',handoff_id:h.handoff_id,tracking_session_id:s.tracking_session_id,symbol:s.symbol,confirmed_action:'WATCH',processed_through_seq:c.handoff_max_event_seq,processed_through_observation_time:c.handoff_max_observation_time,request_fingerprint:'a'.repeat(64),review_id:'REVIEW-TEST-BROWSER',source:'V2B_MANUAL_ACCEPT'};
 await source.locator('#source-ack').setInputFiles({name:'test-native-ack.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(ack))});await source.locator('#source-import').click();await wait(async()=>await source.locator('.acked-purple').count()>0,'actual native receipt badge');checks.native_ack_badge_after_actual_transaction='PASS';
 await source.locator('#source-import').click();await sleep(400);assert.equal((await get('/api/data-observation/state')).facts.filter(f=>f.kind==='ACK_RECEIPT').length,1);checks.native_ack_duplicate_idempotent='PASS';
 assert.equal(pageerror.length,0);assert.equal(console_error.length,0);ok=true;
}catch(e){checks.failure=e.stack;console.error(e.stack);}
finally{fs.writeFileSync(path.join(out,'browser.json'),JSON.stringify({status:ok?'PASS':'FAIL',checks,pageerror,console_error,timings},null,2));await browser.close();}
process.exitCode=ok?0:1;
