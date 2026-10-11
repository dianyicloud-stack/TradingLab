const fs=require('fs'),path=require('path'),{execFileSync}=require('child_process');
const {chromium}=require('./dev/browser.cjs');
const [base,owner,out,secondsText]=process.argv.slice(2),seconds=Number(secondsText),sleep=ms=>new Promise(r=>setTimeout(r,ms));
const result={status:'RUNNING',started:new Date().toISOString(),requestedSeconds:seconds,checks:[],errors:[],consoleErrors:[],externalErrors:[],routes:{},samples:[],checkpoints:[],peakInflight:{},failures:[],requestCount:0};
const bounded=(list,v,max=160)=>{list.push(v);if(list.length>max)list.shift();};
function record(route,ms,status,phase){const key=phase+' '+route;const v=result.routes[key]??={count:0,failures:0,times:[]};v.count++;if(status==='failed'||status>=400)v.failures++;bounded(v.times,ms,4000);}
function save(){fs.writeFileSync(path.join(out,'browser.json'),JSON.stringify(result,null,2));}
(async()=>{const browser=await chromium.launch({headless:true}),context=await browser.newContext({viewport:{width:1440,height:1000}}),page=await context.newPage();result.browser=browser.version();
let phase='warmup',collecting=true,navigating=false,inflight=new Map(),pending=new Map();const cdp=await context.newCDPSession(page);await cdp.send('Performance.enable');
page.on('pageerror',e=>bounded(result.errors,e.message));page.on('console',m=>{if(m.type()!=='error')return;const v={text:m.text(),location:m.location(),phase};bounded(m.location().url.startsWith(base)?result.consoleErrors:result.externalErrors,v)});
page.on('request',r=>{if(!r.url().startsWith(base))return;const route=new URL(r.url()).pathname;pending.set(r,{start:Date.now(),route,phase});inflight.set(route,(inflight.get(route)||0)+1);result.peakInflight[phase+' '+route]=Math.max(result.peakInflight[phase+' '+route]||0,inflight.get(route));result.requestCount++;});
async function finish(r,status){const x=pending.get(r);if(!x||!collecting)return;pending.delete(r);inflight.set(x.route,Math.max(0,(inflight.get(x.route)||0)-1));const classified=status==='failed'&&navigating?'navigation-cancel':x.phase;record(x.route,Date.now()-x.start,status,classified);if(status==='failed')bounded(result.failures,{route:x.route,reason:r.failure()?.errorText,phase:classified});
const t=r.timing();if(result.samples.length<100)result.samples.push({url:r.url(),phase:x.phase,status,timing:t});}
page.on('requestfinished',async r=>finish(r,(await r.response())?.status()||0));page.on('requestfailed',r=>finish(r,'failed'));
await cdp.send('Network.enable');const initiators=[];cdp.on('Network.requestWillBeSent',e=>{if(e.request.url.startsWith(base)&&initiators.length<32)initiators.push({url:e.request.url,type:e.initiator.type,stack:e.initiator.stack?.callFrames?.slice(0,2)});});
const check=(v,text)=>{if(!v)throw Error(text);result.checks.push(text);};
async function get(url){const r=await fetch(url);return r.json();}
async function ownerMode(body){await fetch(owner+'/test/control',{method:'POST',body:JSON.stringify(body)});}
async function waitReady(route){navigating=true;try{await page.goto(base+route,{waitUntil:'domcontentloaded',timeout:60000});await page.waitForSelector(route==='/live'?'.advisory-card':'#observation-table td',{timeout:60000});}finally{navigating=false;}}
async function checkpoint(label){const p=await cdp.send('Performance.getMetrics'),dom=await cdp.send('Memory.getDOMCounters');let resources={};try{resources=JSON.parse(fs.readFileSync(path.join(out,'resources.json')));}catch{}
let processMemory=null;try{const session=await browser.newBrowserCDPSession(),info=await session.send('SystemInfo.getProcessInfo');await session.detach();const ids=info.processInfo.map(p=>Number(p.id)).filter(Number.isInteger);processMemory=JSON.parse(execFileSync('powershell.exe',['-NoProfile','-Command',`Get-Process -Id ${ids.join(',')} -ErrorAction SilentlyContinue | Select-Object Id,WorkingSet64,PrivateMemorySize64,HandleCount | ConvertTo-Json -Compress`],{encoding:'utf8',windowsHide:true,timeout:10000}));}catch{}
result.checkpoints.push({label,at:new Date().toISOString(),dom,browserMetrics:p.metrics.filter(m=>['JSHeapUsedSize','JSHeapTotalSize','Documents','Nodes','JSEventListeners'].includes(m.name)),processMemory,web:resources.memory,server:resources.timings&&{active:resources.timings.active,peak:resources.timings.peak,completed:resources.timings.completed},producer:await get(owner+'/test/stats')});save();}
try{
 await waitReady('/live');await sleep(4000);await waitReady('/data-observation');await sleep(3000);
 if(!out.includes('-load')){
  phase='functional';await waitReady('/live');
  await page.evaluate(()=>{window.originalFetch=window.fetch;window.settingsCalls=0;window.settingsActive=0;window.settingsPeak=0;window.fetch=(url,options)=>{if(!String(url).includes('/api/live/advisory/settings'))return originalFetch(url,options);settingsCalls++;settingsActive++;settingsPeak=Math.max(settingsPeak,settingsActive);return new Promise((resolve,reject)=>{let done=false;const finish=fn=>{if(done)return;done=true;settingsActive--;clearTimeout(timer);fn();};const timer=setTimeout(()=>finish(()=>originalFetch(url,options).then(resolve,reject)),7500);options.signal.addEventListener('abort',()=>finish(()=>reject(options.signal.reason)),{once:true});});};});
  // Simulate resume to trigger settings revalidation after a fresh document.
  await sleep(33000);check(await page.evaluate(()=>settingsPeak)<=1,'slow settings has at most one in-flight request');
  await page.evaluate(()=>window.fetch=originalFetch);await sleep(9000);check(await page.locator('.advisory-card').count()===3,'settings timeout preserves all stock cards');
  await page.click('#expand-all');const control=page.locator('.advisory-card select').first();await control.focus();await page.evaluate(()=>window.focusedControl=document.activeElement);await sleep(3000);check(await page.evaluate(()=>document.activeElement===focusedControl&&document.contains(focusedControl)),'editing focus survives refresh');
  await page.getByText('AI设置',{exact:true}).first().click();await page.locator('#advisory-debounce').fill('7');await sleep(2500);check(await page.locator('#advisory-debounce').inputValue()==='7','unsaved settings preserved');
  const requests=result.requestCount;await page.evaluate(()=>{Object.defineProperty(document,'hidden',{configurable:true,get:()=>true});document.dispatchEvent(new Event('visibilitychange'));});await sleep(7000);const hiddenStart=result.requestCount;await sleep(3000);check(result.requestCount===hiddenStart,'hidden display issues no new requests');
  await page.evaluate(()=>{delete document.hidden;document.dispatchEvent(new Event('visibilitychange'));window.dispatchEvent(new Event('focus'));});await sleep(3000);check(result.requestCount>hiddenStart,'resume restarts one refresh cycle');
  await waitReady('/data-observation');const old=await page.locator('#observation-table tbody').textContent().catch(()=>page.locator('#observation-table').textContent());await ownerMode({paused:true});
  const state1=await get(base+'/api/data-observation/state?view=display');const start=Date.now();const state2=await get(base+'/api/data-observation/state?view=display&since='+state1.display_revision);check(state2.unchanged===true&&Date.now()-start<1000,'since unchanged is immediate conditional read, not long poll');
  await sleep(6000);const state3=await get(base+'/api/data-observation/state?view=display');check(state1.fact_version===state3.fact_version,'no new market data does not advance fact version');
  await ownerMode({error:true});await sleep(8500);check(await page.locator('#observation-table td').count()>0,'owner error retains last successful table');
  await ownerMode({error:false,paused:false});await sleep(6000);check((await page.locator('#data-status').textContent()).includes('已更新'),'owner recovery restores current display');
  await ownerMode({delay:4});await sleep(6500);check(await page.locator('#observation-table td').count()>0,'IPC timeout retains table');await ownerMode({delay:0});await sleep(6000);
  await page.evaluate(()=>{const n=document.querySelector('#observation-scroll');n.scrollTop=100;n.scrollLeft=200;window.savedScroll=[n.scrollTop,n.scrollLeft];});await sleep(3000);check(await page.evaluate(()=>{const n=document.querySelector('#observation-scroll');return n.scrollTop===savedScroll[0]&&n.scrollLeft===savedScroll[1]}),'table scroll preserved during updates');
  const options=await page.locator('#data-symbol option').evaluateAll(ns=>ns.map(n=>n.value));await page.selectOption('#data-symbol',options[1]);await page.selectOption('#data-symbol',options[0]);await page.reload();await page.waitForSelector('#observation-table td');
  for(let i=0;i<20;i++){await waitReady(i%2?'/data-observation':'/live');await sleep(250);}check(true,'20 Live / Observation navigations and reload completed');
  await page.screenshot({path:path.join(out,'functional.png'),fullPage:true});
 }
 phase='normal';const started=Date.now();let nextCheckpoint=1800,nextNav=60;await waitReady('/live');await checkpoint('start');
 while(Date.now()-started<seconds*1000){
  const elapsed=(Date.now()-started)/1000;
  if(elapsed>=nextNav){await waitReady(Math.floor(nextNav/60)%2?'/data-observation':'/live');nextNav+=60;}
  if(elapsed>=nextCheckpoint){await checkpoint('30m');nextCheckpoint=Infinity;}
  // Low-frequency direct shell/resource samples, separate from browser polling.
  for(const route of ['/live','/assets/live.js','/assets/live.css','/data-observation','/assets/data-observation.js']){const start=Date.now();try{const response=await fetch(base+route,{signal:AbortSignal.timeout(20000)});await response.arrayBuffer();record(route,Date.now()-start,response.status,'direct-normal');}catch{record(route,Date.now()-start,'failed','direct-normal');}}
  if(result.checkpoints.length<80&&Math.floor(elapsed/60)>result.checkpoints.filter(x=>x.label.startsWith('sample')).length)await checkpoint('sample '+Math.floor(elapsed/60)+'m');
  result.elapsedSeconds=(Date.now()-started)/1000;save();await sleep(5000);
 }
 await checkpoint(seconds>=3600?'60m':'short-final');result.elapsedSeconds=(Date.now()-started)/1000;
 check(result.errors.length===0,'pageerror zero');check(result.consoleErrors.length===0,'project console.error zero');
 check(Object.entries(result.routes).filter(([k])=>k.startsWith('normal ')).every(([,v])=>v.failures===0),'normal phase has no failed reads');
 result.status='PASS';result.sustainedAcceptance=seconds>=3600&&result.elapsedSeconds>=3600?'PASS':'NOT_RUN_60_MINUTES';
}catch(e){result.status='FAIL';result.error=e.stack;}finally{
 collecting=false;result.finished=new Date().toISOString();result.initiators=initiators;
 for(const row of Object.values(result.routes)){const sorted=[...row.times].sort((a,b)=>a-b);row.p50=sorted[Math.max(0,Math.ceil(sorted.length*.5)-1)];row.p95=sorted[Math.max(0,Math.ceil(sorted.length*.95)-1)];row.timeoutRate=row.failures/row.count;delete row.times;}
 await context.close();await browser.close();save();console.log(JSON.stringify({status:result.status,error:result.error,seconds:result.elapsedSeconds,checks:result.checks}));process.exitCode=result.status==='PASS'?0:1;
}})();
