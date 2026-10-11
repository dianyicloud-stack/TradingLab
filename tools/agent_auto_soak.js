const fs=require('fs'),path=require('path');
const {chromium}=require('./dev/browser.cjs');
const [base,out,secondsText]=process.argv.slice(2),seconds=Number(secondsText),sleep=ms=>new Promise(r=>setTimeout(r,ms));
const result={status:'RUNNING',started:new Date().toISOString(),pageerror:[],console_error:[],external_console_error:[],routes:{},peak_inflight:{},checkpoints:[],navigations:0};
const save=()=>fs.writeFileSync(path.join(out,'browser.json'),JSON.stringify(result,null,2));
(async()=>{const browser=await chromium.launch({headless:true}),page=await browser.newPage({viewport:{width:1440,height:1000}});
const pending=new Map(),active={},cdp=await page.context().newCDPSession(page);await cdp.send('Performance.enable');
page.on('pageerror',e=>result.pageerror.push(e.message));page.on('console',m=>{if(m.type()==='error')(m.location().url.startsWith(base)?result.console_error:result.external_console_error).push({text:m.text(),url:m.location().url})});
page.on('request',r=>{if(!r.url().startsWith(base))return;const key=new URL(r.url()).pathname;pending.set(r,{key,start:Date.now()});active[key]=(active[key]||0)+1;result.peak_inflight[key]=Math.max(result.peak_inflight[key]||0,active[key]);});
page.on('requestfinished',async r=>{const v=pending.get(r);if(!v)return;pending.delete(r);active[v.key]--;const row=result.routes[v.key]??={count:0,errors:0,times:[]};row.count++;row.times.push(Date.now()-v.start);if(row.times.length>4000)row.times.shift();if((await r.response())?.status()>=400)row.errors++;});
page.on('requestfailed',r=>{const v=pending.get(r);if(v){pending.delete(r);active[v.key]--;result.navigation_cancellations=(result.navigation_cancellations||0)+1;}});
try{
 await page.goto(base+'/live');await page.waitForSelector('.advisory-card',{timeout:30000});const started=Date.now();let nextNav=60,nextSample=0;
 while(Date.now()-started<seconds*1000){const elapsed=(Date.now()-started)/1000;
  if(elapsed>=nextNav){const route=['/live','/data-observation','/system/market-source'][result.navigations%3];await page.goto(base+route,{waitUntil:'domcontentloaded',timeout:30000});result.navigations++;nextNav+=60;}
  if(elapsed>=nextSample){const performance=await cdp.send('Performance.getMetrics');result.checkpoints.push({seconds:elapsed,heap:performance.metrics.find(m=>m.name==='JSHeapUsedSize')?.value,inflight:{...active}});nextSample+=60;}
  for(const route of ['/live','/data-observation','/api/live/advisory/settings']){const start=Date.now(),r=await fetch(base+route);await r.text();const row=result.routes['direct '+route]??={count:0,errors:0,times:[]};row.count++;row.times.push(Date.now()-start);if(!r.ok)row.errors++;}
  result.elapsed_seconds=elapsed;save();await sleep(5000);
 }
 result.elapsed_seconds=(Date.now()-started)/1000;await page.goto(base+'/live');await page.waitForSelector('.advisory-card');await page.screenshot({path:path.join(out,'final-live.png'),fullPage:true});
 if(result.pageerror.length||result.console_error.length||Object.values(result.routes).some(r=>r.errors))throw Error('Browser/API errors; inspect evidence');
 if((result.peak_inflight['/api/live/advisory/settings']||0)>1)throw Error('overlapping settings requests');
 result.status='PASS';
}catch(e){result.status='FAIL';result.error=e.stack;result.error_details={name:e.name,code:e.code,cause:e.cause&&{name:e.cause.name,code:e.cause.code,message:e.cause.message,syscall:e.cause.syscall}};}finally{for(const r of Object.values(result.routes)){r.times.sort((a,b)=>a-b);r.p50=r.times[Math.floor(r.times.length*.5)];r.p95=r.times[Math.min(r.times.length-1,Math.floor(r.times.length*.95))];delete r.times;}result.finished=new Date().toISOString();save();await browser.close();process.exitCode=result.status==='PASS'?0:1;}})();
