const fs=require('fs'),path=require('path');
const {chromium}=require('./dev/browser.cjs');
const [base,out,phase]=process.argv.slice(2),sleep=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{const browser=await chromium.launch({headless:true}),context=await browser.newContext({viewport:{width:1440,height:1000}});await context.tracing.start({screenshots:true,snapshots:true});
const page=await context.newPage(),errors=[],consoleErrors=[],result={phase,browser:browser.version(),viewport:'1440x1000',started:new Date().toISOString(),errors,consoleErrors};
page.on('pageerror',e=>errors.push(e.message));page.on('console',e=>{if(e.type()==='error')consoleErrors.push(e.text())});
await page.addInitScript(()=>{window.measure={longTasks:[],mutations:0};new PerformanceObserver(list=>{for(const e of list.getEntries())measure.longTasks.push(e.duration)}).observe({entryTypes:['longtask']});new MutationObserver(list=>measure.mutations+=list.length).observe(document,{subtree:true,childList:true});});
try{
let start=Date.now();await page.goto(base+'/live');await page.waitForSelector('.stock-toggle');result.liveReadyMs=Date.now()-start;
await page.screenshot({path:path.join(out,'live-collapsed.png'),fullPage:true});const toggles=[];
for(let i=0;i<8;i++){const n=page.locator('.advisory-card').first();const hidden=await n.locator('.stock-body').isHidden();start=Date.now();await n.locator('.stock-toggle').click();await page.waitForFunction(({hidden})=>document.querySelector('.stock-body').hidden!==hidden,{hidden});toggles.push(Date.now()-start);await sleep(120);}
result.toggleMs=toggles;result.toggleP95Ms=[...toggles].sort((a,b)=>a-b)[Math.ceil(toggles.length*.95)-1];
await page.locator('.stock-toggle').first().click();await page.waitForSelector('.stock-body:not([hidden])');
await page.evaluate(()=>{window.savedCard=document.querySelector('.advisory-card');window.savedSelect=savedCard.querySelector('select');window.savedDetail=savedCard.querySelector('details');window.savedDetail.open=true;});
await page.request.post(base+'/test/tick',{data:{}});await sleep(4500);
result.liveNodesRetained=await page.evaluate(()=>({card:savedCard===document.querySelector('.advisory-card'),select:savedSelect===document.querySelector('.advisory-card select'),details:savedDetail===document.querySelector('.advisory-card details')}));
await page.screenshot({path:path.join(out,'live-expanded.png'),fullPage:true});result.liveMetrics=await page.evaluate(()=>measure);
start=Date.now();await page.goto(base+'/data-observation');await page.waitForSelector('#observation-table td');result.observationReadyMs=Date.now()-start;
await page.evaluate(()=>{window.savedRow=document.querySelector('#observation-table tr:last-child');window.savedChart=document.querySelector('#amount-chart svg');});await sleep(2900);
result.observationNodesRetained=await page.evaluate(()=>({row:savedRow===document.querySelector('#observation-table tr:last-child'),chart:savedChart===document.querySelector('#amount-chart svg')}));
result.observationRows=await page.locator('#observation-table tr').count();await page.screenshot({path:path.join(out,'observation.png'),fullPage:true});
start=Date.now();await page.goto(base+'/system');result.systemReadyMs=Date.now()-start;await page.screenshot({path:path.join(out,'system.png'),fullPage:true});

if(phase!=='before'){
 const check=(ok,message)=>{if(!ok)throw Error(message);(result.checks??=[]).push(message)};
 check(Object.values(result.liveNodesRetained).every(Boolean),'Live stable card/select/details');check(Object.values(result.observationNodesRetained).every(Boolean),'Observation stable row/chart');
 await page.goto(base+'/live');await page.waitForSelector('.stock-toggle');
 await page.click('#expand-all');await page.waitForFunction(()=>[...document.querySelectorAll('.stock-body')].every(n=>!n.hidden));
 check(await page.locator('.stock-body:visible').count()===3,'all three stocks expand locally');
 const stock=page.locator('.advisory-card').first();await stock.locator('select[aria-label="AI自动分析"]').focus();await page.evaluate(()=>window.editNode=document.activeElement);
 await page.request.post(base+'/test/tick',{data:{}});await sleep(2500);check(await page.evaluate(()=>editNode===document.activeElement&&document.contains(editNode)),'focused select survives facts update');
 await page.locator('h1').click();const oldOpinion=await stock.getAttribute('data-advisory-id');const oldText=await stock.locator('.opinion-brief').textContent();await page.request.post(base+'/test/opinion',{data:{}});await sleep(2500);
 check(await stock.getAttribute('data-advisory-id')===oldOpinion,'new opinion does not replace reading version');check(await stock.locator('.opinion-brief').textContent()===oldText,'reading text immutable until explicit view');
 await stock.locator('.new-opinion-notice').click();check(await stock.getAttribute('data-advisory-id')!==oldOpinion,'explicit new opinion selects precise version');
 await page.click('#collapse-all');check(await page.locator('.stock-body:visible').count()===0,'collapse all immediate');await sleep(600);await page.reload();await page.waitForSelector('.stock-toggle');check(await page.locator('.stock-body:visible').count()===0,'collapse preference survives reload');
 await page.click('#expand-all');await sleep(500);await page.screenshot({path:path.join(out,'three-expanded.png'),fullPage:true});
 await page.goto(base+'/data-observation');await page.waitForSelector('#observation-table td');
 check(await page.locator('#observation-table th').count()===31,'complete original columns plus time provenance');
 await page.evaluate(()=>{const box=document.querySelector('#observation-scroll');box.scrollTop=100;box.scrollLeft=400;window.tableScroll=[box.scrollTop,box.scrollLeft];window.pageTop=scrollY;});
 await page.request.post(base+'/test/observation',{data:{}});await sleep(2900);
 check(await page.evaluate(()=>{const b=document.querySelector('#observation-scroll');return b.scrollTop===tableScroll[0]&&b.scrollLeft===tableScroll[1]&&scrollY===pageTop}),'historical reading does not jump on appended row');
 check(await page.locator('#observation-new').isVisible(),'new row notice when reading history');
 await page.selectOption('#data-symbol','sh688696');check((await page.locator('th[data-column="boardChange"]').textContent()).includes('测试板块1'),'second stock board title');await page.selectOption('#data-symbol','bj920161');
 check(await page.evaluate(()=>document.querySelector('#observation-scroll').scrollTop===tableScroll[0]),'per-stock table scroll restored');
 await page.request.post(base+'/test/board',{data:{}});await sleep(2800);
 check((await page.locator('th[data-column="boardChange"]').textContent()).includes('新确认板块'),'confirmed board title updated');
 check((await page.locator('td[data-column="boardChange"]').first().textContent()).includes('测试板块0'),'old row retains original board source');
 await page.getByText('跟踪设置',{exact:true}).click();await page.locator('#tracking-form [name="symbol"]').fill('bj920161');await page.locator('#tracking-form [name="board_code"]').fill('REJECTED');await page.locator('#tracking-form [name="board_name"]').fill('未确认板块');
 await page.evaluate(()=>{window.savedFetch=window.fetch;window.fetch=(url,...args)=>String(url).includes('/api/data-observation/commands')?Promise.reject(new Error('TEST_BOARD_REJECTED')):savedFetch(url,...args);});
 await page.click('#update-board');await page.waitForFunction(()=>document.querySelector('#data-status').textContent.includes('TEST_BOARD_REJECTED'));
 check((await page.locator('th[data-column="boardChange"]').textContent()).includes('新确认板块'),'rejected board command preserves confirmed title');
 await page.evaluate(()=>{window.fetch=window.savedFetch;window.fetch=async(url,...args)=>{const response=await savedFetch(url,...args);if(String(url).includes('/api/data-observation/state'))await new Promise(r=>setTimeout(r,1600));return response;};});
 await page.click('#data-refresh');await page.selectOption('#data-symbol','sh688696');await sleep(2100);
 check((await page.locator('th[data-column="boardChange"]').textContent()).includes('测试板块1'),'late response preserves selected stock board');
 check(!(await page.locator('td[data-column="boardChange"]').first().textContent()).includes('测试板块0'),'late response does not mix historical board rows');
 await page.evaluate(()=>window.fetch=window.savedFetch);await page.selectOption('#data-symbol','bj920161');await page.getByText('跟踪设置',{exact:true}).click();
 check(await page.locator('td.quality-pending').count()>0,'untrusted amount amber');
 check(await page.locator('td[data-column="amount"].market-up').count()===0,'positive turnover amount is not directional flow');
 await page.getByText('显示列',{exact:true}).click();await page.click('#columns-common');check(await page.locator('#observation-table th').count()===8,'common column preference');await page.reload();await page.waitForSelector('#observation-table td');check(await page.locator('#observation-table th').count()===8,'column preference restored');await page.getByText('显示列',{exact:true}).click();await page.click('#columns-full');
 await page.screenshot({path:path.join(out,'board-history.png'),fullPage:true});
 await page.setViewportSize({width:390,height:844});await page.goto(base+'/live');await page.waitForSelector('.stock-toggle');check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2),'mobile no page horizontal overflow');await page.screenshot({path:path.join(out,'mobile-live.png'),fullPage:true});await page.goto(base+'/data-observation');await page.waitForSelector('#observation-table td');check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2),'mobile table scroll confined');await page.screenshot({path:path.join(out,'mobile-observation.png'),fullPage:true});
 await page.setViewportSize({width:1440,height:1000});await page.goto(base+'/system');await page.click('#system-diagnose');await page.waitForFunction(()=>!document.querySelector('#system-diagnose').disabled);check((await page.locator('#system-status').textContent()).includes('最近检查'),'explicit background diagnostics');
 check(errors.length===0&&consoleErrors.length===0,'pageerror and console.error zero');
 const seconds=Number(process.env.UI_SOAK_SECONDS||0);result.soak={requestedSeconds:seconds,status:seconds?'RUNNING':'NOT_RUN',cycles:0,requests:0};
 if(seconds){const end=Date.now()+seconds*1000;page.on('request',r=>{if(r.url().startsWith(base))result.soak.requests++});while(Date.now()<end){await page.request.post(base+'/test/tick',{data:{}});for(const route of ['/live','/data-observation','/system']){await page.goto(base+route);await sleep(900);}result.soak.cycles++;if(result.soak.cycles%10===0)fs.writeFileSync(path.join(out,'soak-progress.json'),JSON.stringify(result.soak));await sleep(2000);}result.soak.status=errors.length||consoleErrors.length?'FAIL':'PASS';}
 result.status='PASS';
}else result.status='RECORDED';

}catch(e){result.status='FAIL';result.error=e.stack;process.exitCode=1;}finally{result.finished=new Date().toISOString();fs.writeFileSync(path.join(out,'metrics.json'),JSON.stringify(result,null,2));await context.tracing.stop({path:path.join(out,'trace.zip')});await browser.close();console.log(JSON.stringify(result));}})();
