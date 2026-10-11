// TEST-only UI races. The borrowed server is the isolated soak namespace.
const fs=require('fs'),path=require('path'),{chromium}=require('./dev/browser.cjs');
const [base,out]=process.argv.slice(2),sleep=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{const browser=await chromium.launch({headless:true}),context=await browser.newContext(),page=await context.newPage(),result={checks:[],errors:[],consoleErrors:[]};
page.on('pageerror',e=>result.errors.push(e.message));page.on('console',e=>{if(e.type()==='error')result.consoleErrors.push(e.text());});
const check=(value,name)=>{if(!value)throw Error(name);result.checks.push(name);};
try{
 const response=await page.request.get(base+'/api/data-observation/state?view=display');const original=await response.json();if(original.source!=='TEST')throw Error('TEST_NAMESPACE_REQUIRED');
 const value=structuredClone(original),session=structuredClone(value.sessions[0]),sid=session.tracking_session_id;session.tracking_session_id+='-HISTORY';session.date='2026-09-16';value.sessions.push(session);
 for(const fact of original.facts.filter(f=>f.kind==='OBSERVATION'&&f.payload.tracking_session_id===sid).slice(0,2)){const row=structuredClone(fact);row.identity+='-HISTORY';row.payload.tracking_session_id=session.tracking_session_id;row.payload.raw.price=123.45;value.facts.push(row);}
 let delay=0;await page.route('**/api/data-observation/state*',async r=>{await sleep(delay);await r.fulfill({status:200,contentType:'application/json',body:JSON.stringify(value)});});
 await page.goto(base+'/data-observation');await page.waitForSelector('#observation-table td');
 await page.selectOption('#data-symbol',session.symbol);delay=1000;await page.click('#data-refresh');await page.selectOption('#data-date','2026-09-16');await sleep(1500);
 check(await page.locator('#data-date').inputValue()==='2026-09-16','late display response preserves selected date');
 check((await page.locator('td[data-column="price"]').first().textContent()).includes('123.45'),'selected date displays its own facts');
 const other=value.sessions.find(s=>s.symbol!==session.symbol&&s.date!=='2026-09-16');await page.selectOption('#data-date',other.date);await page.selectOption('#data-symbol',other.symbol);await sleep(2700);
 check(!(await page.locator('td[data-column="price"]').first().textContent()).includes('123.45'),'stock switch cannot reuse other date or stock rows');
 await page.goto(base+'/live');await page.waitForSelector('.advisory-card');
 await page.evaluate(()=>{window.testCalls=0;window.testActive=0;window.testPeak=0;window.testAborts=[];const original=window.fetch;window.fetch=(url,options)=>{if(!String(url).includes('/api/live/advisory/settings'))return original(url,options);testCalls++;testActive++;testPeak=Math.max(testPeak,testActive);return new Promise((resolve,reject)=>{options.signal.addEventListener('abort',()=>{testActive--;testAborts.push(options.signal.reason.name);reject(options.signal.reason);},{once:true});});};});
 await sleep(41000);const evidence=await page.evaluate(()=>({calls:testCalls,peak:testPeak,aborts:testAborts}));result.settings=evidence;
 check(evidence.calls>=1&&evidence.peak===1&&evidence.aborts.includes('TimeoutError'),'settings timeout was actually exercised, one in flight');
 check(await page.locator('.advisory-card').count()===3,'settings failure preserves three current stock cards');
 check(!result.errors.length&&!result.consoleErrors.length,'zero browser errors');result.status='PASS';
}catch(e){result.status='FAIL';result.error=e.stack;}finally{fs.mkdirSync(out,{recursive:true});fs.writeFileSync(path.join(out,'browser.json'),JSON.stringify(result,null,2));await context.close();await browser.close();console.log(JSON.stringify(result));process.exitCode=result.status==='PASS'?0:1;}})();
