// Read-only browser check. No AI, notifications, settings or account commands.
const {createRequire}=require('node:module'),path=require('node:path');
const req=createRequire(__filename);
const {chromium}=req(path.resolve(path.dirname(process.execPath),'../node_modules/playwright'));
(async()=>{
 const base=process.argv[2];if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base))throw Error('LOOPBACK_ONLY');
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe'});
 const page=await browser.newPage(),errors=[],consoleErrors=[],pages=[],blocked=[];
 page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')consoleErrors.push(m.text());});
 await page.route('**/*',route=>{
   const request=route.request();
   const readPosition=request.method()==='POST' && /^\/api\/live\/[^/]+\/read$/.test(new URL(request.url()).pathname);
   const target=new URL(request.url());
   // Local security software injects this external script into loopback HTML.
   // Keep the application check offline without reporting a harness-induced network failure.
   if(target.pathname==='/FD126C42-EBFA-4E12-B309-BB3FDD723AC1/main.js' && request.resourceType()==='script')return route.fulfill({status:200,contentType:'application/javascript',body:''});
   if(!request.url().startsWith(base+'/')||(!['GET','HEAD'].includes(request.method())&&!readPosition)){blocked.push({method:request.method(),path:target.pathname});return route.abort();}
   return route.continue();
 });
 try{
  for(const route of ['/live','/data-observation','/account','/system']){
   const start=Date.now(),response=await page.goto(base+route);await page.waitForTimeout(1500);
   const links=await page.locator('nav[aria-label="主导航"] a').evaluateAll(nodes=>nodes.map(n=>n.getAttribute('href')));
   if(JSON.stringify(links)!==JSON.stringify(['/live','/data-observation','/account','/system']))throw Error('NAVIGATION_MISMATCH '+route);
   if(response.status()!==200)throw Error('PAGE_FAILED '+route);
   if(route==='/live'){
    if(await page.locator('#mode-simulation,#formal-center').count())throw Error('RETIRED_LIVE_UI');
    await page.locator('#advisory-cards').waitFor();
    await page.evaluate(()=>window.scrollTo(0,document.body.scrollHeight));
   }
   if(route==='/account' && await page.locator('#account-new-replay').count())throw Error('RETIRED_ACCOUNT_UI');
   if(route==='/data-observation' && await page.locator('#source-handoff,#source-import,#formal-capability,a[href="/decisions"]').count())throw Error('RETIRED_OBSERVATION_UI');
   pages.push({route,status:response.status(),elapsed_ms:Date.now()-start});
  }
  console.log(JSON.stringify({pages,pageerror:errors,console_error:consoleErrors,blocked}));
  if(errors.length||consoleErrors.length)process.exitCode=1;
 }finally{await browser.close();}
})().catch(e=>{console.error(e.message);process.exitCode=1;});
