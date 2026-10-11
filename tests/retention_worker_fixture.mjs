// TEST subprocess transport only. Production runtime/normalizers remain unchanged.
import {createInterface} from 'node:readline';
import {createRuntime} from '../engines/live/market_agent/runtime.mjs';
globalThis.fetch=()=>{throw Error('REAL_NETWORK_FORBIDDEN_IN_TEST')};
let runtime,clock;
for await(const line of createInterface({input:process.stdin,crlfDelay:Infinity})){
 try{const input=JSON.parse(line);if(input.op==='initialize'){
  clock=input.now;runtime=createRuntime(input.state,{now:clock,network:true,transport:{loadJsonpVariable:async url=>{
   const u=new URL(url);if(!u.pathname.includes('getKLineData'))throw Error('FIXTURE_ENDPOINT_NOT_AVAILABLE');
   const scale=Number(u.searchParams.get('scale')),count=Number(u.searchParams.get('datalen'));
   const today=clock.slice(0,10),rows=[];
   for(let d=35;d>=1;d--){const date=new Date(today+'T00:00:00Z');date.setUTCDate(date.getUTCDate()-d);if([0,6].includes(date.getUTCDay()))continue;
    const day=date.toISOString().slice(0,10);for(let i=0;i<(scale===240?1:48);i++)rows.push({day:day+' '+(scale===240?'15:00:00':`${String(9+Math.floor((35+i*5)/60)).padStart(2,'0')}:${String((35+i*5)%60).padStart(2,'0')}:00`),open:10,high:11,low:9,close:10,volume:1000,amount:10000});}
   return rows.slice(-count);
  },loadJsonpCallback:async()=>{throw Error('FIXTURE_ENDPOINT_NOT_AVAILABLE')}}});
  process.stdout.write(JSON.stringify({ok:true,value:{fixture:true}})+'\n');continue;
 }
 const value=await runtime.execute(input);process.stdout.write(JSON.stringify({ok:true,value})+'\n');
 }catch(e){process.stdout.write(JSON.stringify({ok:false,error:e.message,code:'TEST_CORE_ERROR'})+'\n');}
}
