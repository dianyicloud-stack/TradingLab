// Read existing results in production; write tests permitted only on an isolated port.
const path=require('node:path'),{createRequire}=require('node:module');
const {chromium}=createRequire(__filename)(path.resolve(path.dirname(process.execPath),'../node_modules/playwright'));
(async()=>{
 const base=process.argv[2],fake=process.argv.includes('--fake-write');
 if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base)||fake&&base.endsWith(':8765'))throw Error('ISOLATED_WRITE_REQUIRED');
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe'}),context=await browser.newContext();
 const errors=[],consoleErrors=[],posts=[];let page=await context.newPage();
 context.on('page',p=>observe(p));observe(page);
 function observe(p){p.on('pageerror',e=>errors.push(e.message));p.on('console',e=>{if(e.type()==='error')consoleErrors.push(e.text());});}
 await context.route('**/*',route=>{const r=route.request(),u=new URL(r.url());
  if(u.pathname==='/FD126C42-EBFA-4E12-B309-BB3FDD723AC1/main.js')return route.fulfill({status:200,contentType:'application/javascript',body:''});
  if(u.origin!==base)return route.abort();
  if(!['GET','HEAD'].includes(r.method())){
   if(/^\/api\/live\/[^/]+\/read$/.test(u.pathname))return route.fulfill({status:200,contentType:'application/json',body:'{}'});
   if(!fake||!['/api/history/analyses','/api/history/preferences'].includes(u.pathname))return route.abort();
   posts.push({path:u.pathname,body:JSON.parse(r.postData())});
  }
  return route.continue();});
 try{
  await page.goto(base+'/live');await page.locator('#history-today:not([hidden])').waitFor();await page.locator('#history-today>summary').click();
  const count=await page.locator('#history-today-items a').count();if(count<1)throw Error('NO_SAVED_RESULTS');
  const href=await page.locator('#history-today-items a').first().getAttribute('href');await page.locator('#history-today-items a').first().click();
  await page.waitForFunction(()=>document.querySelector('#history-opinion-status')?.textContent.includes('已完成'));
  const body=await page.locator('#history-opinion-body').innerText();if(/volume_context|\bratio\b|\bamount\b|\bnull\b/.test(body))throw Error('RAW_TECHNICAL_BODY');
  if(!await page.locator('#live-center').isHidden())throw Error('HISTORY_NOT_ISOLATED');
  const format=await page.evaluate(()=>[9999,10000,10500,100000,105000,1000000,2354661,32713743,-10500].map(readingFormat.volume));
  if(JSON.stringify(format)!==JSON.stringify(['9999','1W','1.05W','10W','10.5W','100W','235.47W','3271.37W','-1.05W']))throw Error('VOLUME_FORMAT');
  for(const route of ['/account','/system','/live'])await page.goto(base+route);
  await page.locator('#history-today:not([hidden])').waitFor();await page.reload();await page.locator('#history-today:not([hidden])').waitFor();
  const second=await context.newPage();await second.goto(base+'/live');await second.locator('#history-today:not([hidden])').waitFor();await second.close();
  await page.goto(base+href);await page.waitForFunction(()=>document.querySelector('#history-opinion-status')?.textContent.includes('已完成'));
  const restored=await page.locator('#history-opinion-body').innerText();if(restored!==body)throw Error('RESULT_CHANGED_ON_NAVIGATION');
  if(fake){
   await page.goto(base+'/data-observation');await page.locator('#history-panel>summary').click();await page.locator('#history-symbol').fill('bj920161');await page.locator('#history-symbol').dispatchEvent('change');await page.waitForTimeout(100);
   await page.locator('#history-mode').selectOption('HISTORY_EOD');await page.locator('#history-date').fill('2026-09-24');await page.locator('#history-volume').selectOption('WEEK');await page.locator('#history-load').click();
   await page.locator('#history-analyze:not([disabled])').waitFor();await page.locator('#history-analyze').click();await page.locator('#history-existing:not([hidden])').waitFor();
   if(!page.url().includes('/data-observation'))throw Error('REUSE_MUST_OFFER_CHOICE');
   await page.locator('#history-existing-link').click();await page.waitForFunction(()=>document.querySelector('#history-opinion-status')?.textContent.includes('已完成'));
   await page.goBack();await page.locator('#history-panel>summary').click().catch(()=>{});
   // Restore form explicitly after navigation; preferences alone are not result authority.
   await page.goto(base+'/data-observation');await page.locator('#history-panel>summary').click();await page.locator('#history-symbol').fill('bj920161');await page.locator('#history-symbol').dispatchEvent('change');await page.waitForTimeout(100);
   await page.locator('#history-mode').selectOption('HISTORY_EOD');await page.locator('#history-date').fill('2026-09-24');await page.locator('#history-volume').selectOption('WEEK');await page.locator('#history-load').click();await page.locator('#history-analyze:not([disabled])').waitFor();await page.locator('#history-analyze').click();await page.locator('#history-existing:not([hidden])').waitFor();
   await page.locator('#history-reanalyze').click();await page.waitForURL(/\/live\?history=/);await page.waitForFunction(()=>document.querySelector('#history-opinion-status')?.textContent.includes('已完成'));
  }
  console.log(JSON.stringify({saved_count:count,navigation_refresh_new_window:true,chinese_body:body,volume:format,history_posts:posts.filter(p=>p.path==='/api/history/analyses').map(p=>({force:p.body.force_reanalysis})),pageerror:errors,console_error:consoleErrors}));
  if(errors.length||consoleErrors.length)process.exitCode=1;
 }finally{await browser.close();}
})().catch(e=>{console.error(e.stack);process.exitCode=1;});
