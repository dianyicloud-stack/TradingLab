const fs=require('fs'),path=require('path');
const {chromium}=require('./dev/browser.cjs');
const [base,out]=process.argv.slice(2),pause=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
  const browser=await chromium.launch({headless:true});
  const context=await browser.newContext({viewport:{width:1440,height:1080}}),page=await context.newPage();
  const result={checks:[],pageerror:[],console_error:[],requests:[],failed_requests:[]};
  page.on('pageerror',e=>result.pageerror.push(e.message));page.on('console',e=>{if(e.type()==='error')result.console_error.push({text:e.text(),location:e.location()});});
  page.on('requestfailed',r=>result.failed_requests.push({url:r.url(),failure:r.failure()}));
  page.on('request',r=>result.requests.push({url:r.url(),method:r.method(),at:Date.now()}));
  result.isolated_external_scripts=[];
  await page.route('**/*',r=>{const url=new URL(r.request().url());if(url.origin===base)return r.continue();
    if(url.hostname.endsWith('.kaspersky-labs.com')){result.isolated_external_scripts.push(url.hostname);return r.fulfill({status:200,body:'/* External security-software injection isolated in TEST. */',contentType:'text/javascript'});}
    return r.abort();});
  const check=(v,name)=>{if(!v)throw Error(name);result.checks.push(name)},stock=page.locator('#stock-bj920161');
  const info=async()=>await(await page.request.get(base+'/test/info')).json();
  let status=1;
  try{
    await page.goto(base+'/live');await stock.waitFor();await stock.locator('.stock-toggle').click();
    const before=await info();check(before.latest.trigger_type==='AUTO_EVENT','actual isolated automatic result is displayed');
    const view=stock.locator('.stock-body > .opinion-brief');
    await view.locator('.judgment-summary').waitFor();
    check(await view.locator('.judgment-summary').count()===1,'one judgment summary');
    check(await view.locator(':scope > .opinion-section').count()===5,'five visually separated reading sections');
    const colors=await view.locator('.delta-grid').evaluate(n=>Object.fromEntries(['change-up','change-down','change-flat'].map(k=>[k,n.querySelector('.'+k)?getComputedStyle(n.querySelector('.'+k)).color:null])));
    check(colors['change-up']==='rgb(180, 35, 53)'&&colors['change-down']==='rgb(19, 115, 70)'&&colors['change-flat']==='rgb(94, 109, 126)','red increase green decrease gray flat');
    check(await view.locator('.time-badge.opinion-cutoff').count()===1&&await stock.locator('.latest-success .time-badge').count()===2,'consistent highlighted cutoff and completion badges');
    await view.locator('.opinion-detail > summary').click();
    check((await view.innerText()).split('价格守住支撑，但量能确认仍不足。').length-1===1,'summary not repeated in expanded details');
    check((await view.innerText()).includes('增强但未确认而非确认'),'mixed Chinese enum sentence translated');
    check(!/STRENGTHENED|CONFIRMED|\bWAIT\b|\bINVALID\b|FAILED WINDOW|INPUT_BUDGET/.test(await stock.innerText()),'visible opinion contains no judgment codes');
    check(await view.locator('img').count()===0&&(await view.innerText()).includes('<img src=x'),'untrusted prose remains text');
    await stock.screenshot({path:path.join(out,'automatic-reading.png')});
    check(await stock.locator('.sync-details').count()===0&&(await stock.locator('.sync-summary').innerText()).includes('数据同步'),'only concise sync status remains');
    await stock.locator('.advisory-history > summary').click();await stock.locator('.history-opinion').first().waitFor();
    check(await stock.locator('.history-opinion').count()===2,'real saved history is bound');
    await stock.locator('.advisory-timeline > summary').click();await stock.locator('.timeline-node').first().waitFor();
    check(await stock.locator('.timeline-node').count()===2,'timeline derives from real saved opinions');
    const other=page.locator('#stock-sh688696');await other.locator('.stock-toggle').click();await other.locator('.advisory-history > summary').click();await other.locator('.history-empty').waitFor();
    check((await other.locator('.history-empty').innerText()).includes('暂无历史意见'),'empty history is explicit and isolated');
    // A malformed successful read exercises retry without inventing an HTTP outage.
    await page.route('**/bj920161/advisory/history?*',r=>r.fulfill({status:200,body:'not-json',contentType:'application/json'}),{times:1});
    await stock.locator('.advisory-history .history-refresh').click();await stock.locator('.history-error').waitFor();
    await stock.locator('.history-retry').click();await stock.locator('.history-opinion').first().waitFor();
    check(await stock.locator('.history-opinion').count()===2,'failed history read is explained and retry recovers');
    result.requests=[];await pause(6500);
    check(result.requests.filter(r=>r.url.includes('/advisory/history')||r.url.includes('/advisory/timeline')).length===0,'polling does not re-request expanded history');
    check(result.requests.filter(r=>new URL(r.url).pathname==='/api/live/stocks').length<=4,'single existing polling cadence preserved');
    check(await view.locator('.opinion-detail').getAttribute('open')!==null,'detail reading survives updates');
    const afterRead=await info();check(afterRead.calls===before.calls&&JSON.stringify(afterRead.cursor)===JSON.stringify(before.cursor)&&afterRead.ledger_count===before.ledger_count,'reading does not invoke AI advance cursor or trade');
    // Existing manual button and explicit no-new-data flow stay intact (fake AI only).
    await page.request.post(base+'/test/append',{data:{}});await stock.getByRole('button',{name:'立即分析',exact:true}).click();await stock.locator('.new-opinion-notice').waitFor();await stock.locator('.new-opinion-notice').click();
    check((await info()).calls===before.calls+1,'manual analyze still uses existing chain exactly once');
    await stock.locator('.advisory-history .history-update').waitFor();
    await stock.locator('.advisory-history .history-refresh').click();
    await page.waitForFunction(()=>document.querySelectorAll('#stock-bj920161 .history-opinion').length===3);
    check(true,'already open history announces and loads new saved opinion');
    await stock.getByRole('button',{name:'立即分析',exact:true}).click();await stock.locator('.force-reanalysis').waitFor({state:'visible'});
    check((await stock.locator('.advisory-message').innerText()).includes('没有新的市场数据')&&(await info()).calls===before.calls+1,'no new data explains without another AI call');
    // Display a backend failure DTO without changing saved opinion, cursor or service logic.
    await page.route('**/api/live/stocks?*',async r=>{const response=await r.fetch(),data=await response.json();const c=data.advisory_cards.find(c=>c.session.symbol==='bj920161');c.health.analysis_status.failure={stage:'INPUT',error_code:'INPUT_BUDGET',reason:'FAILED WINDOW：INPUT_BUDGET',retryable:false};await r.fulfill({response,json:data});});
    await stock.locator('.analysis-failure').waitFor();check((await stock.locator('.analysis-failure').innerText()).includes('输入预算不足')&&!/FAILED WINDOW|INPUT_BUDGET/.test(await stock.innerText()),'failure codes localized without altering opinion');
    await page.unroute('**/api/live/stocks?*');
    await stock.scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,'desktop.png'),fullPage:true});
    await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(out,'mobile.png'),fullPage:true});
    check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'mobile has no horizontal overflow');
    check(result.pageerror.length===0&&result.console_error.length===0,'pageerror=0 console.error=0');status=0;
  }catch(e){result.failure=e.stack;await page.screenshot({path:path.join(out,'failure.png'),fullPage:true}).catch(()=>{});}
  finally{result.status=status===0?'PASS':'FAIL';fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify({status:result.status,checks:result.checks,failure:result.failure,pageerror:result.pageerror,console_error:result.console_error}));await browser.close();process.exitCode=status;}
})();
