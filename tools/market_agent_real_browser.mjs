// Read-only production UI check. No buttons invoking analysis or source commands.
import fs from 'node:fs';import path from 'node:path';import assert from 'node:assert/strict';import {createRequire} from 'node:module';
const require=createRequire(import.meta.url),{chromium}=require('./dev/browser.cjs');
const out=path.resolve('artifacts/market_agent'),errors=[],consoleErrors=[],writes=[],checks={};
const browser=await chromium.launch({headless:true});let success=false;
try{
 const context=await browser.newContext({viewport:{width:1440,height:1050}});
 context.on('page',page=>{page.on('pageerror',e=>errors.push(e.message));page.on('console',e=>{if(e.type()==='error')consoleErrors.push(e.text())});page.on('request',r=>{if(r.url().startsWith('http://127.0.0.1:8765')&&!['GET','HEAD'].includes(r.method()))writes.push(r.method()+' '+r.url())});});
 const page=await context.newPage();await page.goto('http://127.0.0.1:8765/live');await page.locator('#live-status').waitFor();await page.waitForTimeout(3300);
 assert(await page.getByRole('link',{name:/数据观察/}).count());checks.navigation='PASS';
 const response=await context.request.get('http://127.0.0.1:8765/api/live/stocks'),stocks=await response.json();assert(stocks.read_model);checks.background_read_model='PASS';
 for(let i=0;i<3;i++){const contextResponse=await context.request.get('http://127.0.0.1:8765/api/live/bj920161/portfolio-context');assert(contextResponse.ok());}checks.portfolio_context_read='PASS';
 await page.screenshot({path:path.join(out,'real-live.png'),fullPage:true});await page.goto('http://127.0.0.1:8765/data-observation');await page.getByText(/后台数据服务尚未启用/).waitFor();checks.no_fake_agent_activation='PASS';await page.screenshot({path:path.join(out,'real-data-observation.png'),fullPage:true});
 await page.waitForTimeout(2700);assert.equal(errors.length,0);assert.equal(consoleErrors.length,0);assert.equal(writes.length,0);checks.read_only='PASS';success=true;
}catch(e){checks.failure=e.stack;console.error(e.stack)}finally{await browser.close();fs.writeFileSync(path.join(out,'real-browser.json'),JSON.stringify({status:success?'PASS':'FAIL',checks,pageerror:errors,console_error:consoleErrors,application_writes:writes},null,2));}
process.exitCode=success?0:1;
