/* Display-only lifecycle. Never abort commands or stop a producer. */
(()=>{'use strict';
window.TradingLabDisplayRefresh=class {
  constructor(read,{period=2500,maxDelay=30000,onError=()=>{},onPause=()=>{}}={}){
    this.read=read;this.period=period;this.maxDelay=maxDelay;this.onError=onError;this.onPause=onPause;
    this.flight=null;this.timer=null;this.requests=new Map();this.failures=0;this.stopped=false;
    this.visibility=()=>document.hidden?this.pause():this.refresh();
    this.hide=()=>{this.stopped=true;this.pause();};this.show=()=>{this.stopped=false;this.refresh();};
    document.addEventListener('visibilitychange',this.visibility);window.addEventListener('pagehide',this.hide);window.addEventListener('pageshow',this.show);
  }
  active(){return !this.stopped&&!document.hidden;}
  pause(){clearTimeout(this.timer);this.timer=null;this.onPause();for(const entry of this.requests.values())entry.controller.abort(new DOMException('Display hidden','AbortError'));}
  request(url,timeout=6000){
    if(this.requests.has(url))return this.requests.get(url).promise;
    if(!this.active())return Promise.reject(new DOMException('Display inactive','AbortError'));
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(new DOMException('Display read timed out','TimeoutError')),timeout);
    const entry={controller};entry.promise=fetch(url,{signal:controller.signal}).then(async r=>{const value=await r.json();if(!r.ok){const e=Error(value.message||value.error||`HTTP ${r.status}`);e.code=value.error;throw e;}return value;}).finally(()=>{clearTimeout(timer);if(this.requests.get(url)===entry)this.requests.delete(url);});
    this.requests.set(url,entry);return entry.promise;
  }
  refresh(){
    clearTimeout(this.timer);this.timer=null;
    if(!this.active())return Promise.resolve();
    if(this.flight)return this.flight;
    this.flight=Promise.resolve().then(()=>this.read()).then(ok=>{this.failures=ok===false?Math.min(this.failures+1,5):0;}).catch(e=>{if(this.active()&&e.name!=='AbortError'){this.failures=Math.min(this.failures+1,5);this.onError(e);}}).finally(()=>{
      this.flight=null;
      if(this.active())this.timer=setTimeout(()=>this.refresh(),Math.min(this.maxDelay,this.period*2**this.failures));
    });return this.flight;
  }
};
})();
