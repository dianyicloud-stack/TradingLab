const fs=require('fs'),path=require('path');
const {chromium}=require(path.resolve(path.dirname(process.execPath),'../node_modules/playwright'));
const [base,out,seconds]=process.argv.slice(2),sleep=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',args:['--disable-background-timer-throttling','--disable-renderer-backgrounding']});
 const results={started_at:new Date().toISOString(),duration_seconds:Number(seconds),variants:{},real_provider_calls:0},clients=[];
 try{
 for(const variant of ['before','after']){
  const context=await browser.newContext({viewport:{width:1440,height:1000}}),page=await context.newPage(),cdp=await context.newCDPSession(page);
  const r=results.variants[variant]={errors:[],console_errors:[],samples:[],interactions:[],request_count:0,api_times:[],security_injections:[]};
  page.on('pageerror',e=>r.errors.push(e.message));page.on('console',e=>{if(e.type()==='error')r.console_errors.push(e.text());});
  page.on('request',()=>r.request_count++);page.on('requestfinished',q=>{if(q.url().includes('/api/')){const t=q.timing();r.api_times.push(t.responseEnd-t.requestStart);if(r.api_times.length>3000)r.api_times.shift();}});
  await page.route('**/*',route=>{const u=new URL(route.request().url());if(u.origin!==base){if(u.hostname.endsWith('.kaspersky-labs.com')){r.security_injections.push(u.hostname);return route.fulfill({status:200,body:'/* TEST external injected script excluded */',contentType:'text/javascript'});}return route.abort();}
   if(variant==='before'&&['/assets/live.js','/assets/live.css'].includes(u.pathname))return route.continue({url:base+u.pathname.replace('live.','live-baseline.')});return route.continue();});
  await page.addInitScript(()=>{window.soakLong=[];new PerformanceObserver(list=>{for(const e of list.getEntries())window.soakLong.push({start:e.startTime,duration:e.duration});if(window.soakLong.length>5000)window.soakLong.splice(0,1000);}).observe({type:'longtask',buffered:true});});
  await cdp.send('Performance.enable');await page.goto(base+'/live');await page.locator('.advisory-card').nth(2).waitFor();
  clients.push({variant,page,cdp,r});
 }
 const started=Date.now();let iteration=0;
 while(true){
  for(const {variant,page,cdp,r} of clients){
   const tracing=iteration===0;let traceDone;
   if(tracing){traceDone=new Promise(resolve=>cdp.once('Tracing.tracingComplete',resolve));await cdp.send('Tracing.start',{categories:'devtools.timeline',transferMode:'ReturnAsStream'});}
   // Real scrolling and expand/read/close interactions, never a simulated clock.
   for(const card of await page.locator('.advisory-card').all()){
    if(await card.getAttribute('data-collapsed')==='true')await card.locator('.stock-toggle').click();
    const h=card.locator('.advisory-history');if(await h.getAttribute('open')===null)await h.locator(':scope > summary').click();
    if(iteration%3===0)await h.locator('.history-refresh').click().catch(()=>{});
    const rows=h.locator('.history-opinion');if(await rows.count()){
     const interaction=await rows.first().evaluate(n=>new Promise(resolve=>{const at=performance.now(),before=n.querySelectorAll('*').length;n.open=!n.open;requestAnimationFrame(()=>requestAnimationFrame(()=>resolve({toggle_to_two_frames_ms:performance.now()-at,expanded:n.open,nodes_before:before,nodes_after:n.querySelectorAll('*').length})));}));r.interactions.push(interaction);
    }
   }
   const frames=await page.evaluate(async()=>{let gaps=[],last=performance.now();for(let i=0;i<90;i++){window.scrollBy(0,i<45?65:-65);await new Promise(requestAnimationFrame);const n=performance.now();gaps.push(n-last);last=n;}return gaps;});
   const metrics=Object.fromEntries((await cdp.send('Performance.getMetrics')).metrics.map(m=>[m.name,m.value])),dom=await cdp.send('Memory.getDOMCounters');
   const ui=await page.evaluate(()=>({nodes:document.querySelectorAll('*').length,long_tasks:window.soakLong.length,long_task_ms:window.soakLong.reduce((s,x)=>s+x.duration,0),history_bodies:document.querySelectorAll('.history-opinion .opinion-brief').length}));
   frames.sort((a,b)=>a-b);const api=r.api_times.slice().sort((a,b)=>a-b);
   r.samples.push({elapsed_seconds:(Date.now()-started)/1000,at:new Date().toISOString(),metrics,dom,...ui,scroll_frame_p95:frames[Math.floor(frames.length*.95)],scroll_frame_max:frames.at(-1),api_p95:api[Math.floor(api.length*.95)]||0,requests:r.request_count});
   if(iteration===0||Math.abs((Date.now()-started)/1000-1800)<35||Number(seconds)*1000-(Date.now()-started)<40000)await page.screenshot({path:path.join(out,variant+'-'+Math.round((Date.now()-started)/1000)+'.png')});
   if(tracing){await cdp.send('Tracing.end');const {stream}=await traceDone;let raw='';while(true){const chunk=await cdp.send('IO.read',{handle:stream});raw+=chunk.data;if(chunk.eof)break;}await cdp.send('IO.close',{handle:stream});
    const summary={};for(const e of JSON.parse(raw).traceEvents||[])if(['Paint','Layout','UpdateLayoutTree','FunctionCall','EventDispatch'].includes(e.name)&&e.ph==='X'){const a=summary[e.name]||={count:0,total_ms:0,max_ms:0};a.count++;a.total_ms+=(e.dur||0)/1000;a.max_ms=Math.max(a.max_ms,(e.dur||0)/1000);}r.render_trace=summary;
   }
   // User-driven route navigation periodically verifies disposal/re-entry.
   if(iteration&&iteration%10===0){await page.goto(base+'/system');await page.goto(base+'/live');await page.locator('.advisory-card').nth(2).waitFor();}
  }
  results.elapsed_seconds=(Date.now()-started)/1000;fs.writeFileSync(path.join(out,'progress.json'),JSON.stringify(results,null,2));iteration++;
  if(Date.now()-started>=Number(seconds)*1000)break;await sleep(Math.min(25000,Number(seconds)*1000-(Date.now()-started)));
 }
 results.finished_at=new Date().toISOString();results.status=Object.values(results.variants).every(v=>!v.errors.length&&!v.console_errors.length)?'PASS':'FAIL';
 }catch(e){results.status='FAIL';results.failure=e.stack;}finally{fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(results,null,2));console.log(JSON.stringify({status:results.status,failure:results.failure,elapsed:results.elapsed_seconds}));await browser.close();process.exitCode=results.status==='PASS'?0:1;}
})();
