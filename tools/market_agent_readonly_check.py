"""Verify newly loaded production READ endpoints do not append protected facts."""
from pathlib import Path
import hashlib,json,subprocess
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'artifacts/market_agent'
def snapshot():
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for folder in ('data/account','data/learning','data/decisions','legacy') for p in (ROOT/folder).rglob('*') if p.is_file()}
before=snapshot();node=Path(__import__('os').environ.get('TRADING_LAB_NODE', str(ROOT/'.dev/runtime/node/node.exe')))
run=subprocess.run([str(node),str(ROOT/'tools/market_agent_real_browser.mjs')],cwd=ROOT,timeout=90)
after=snapshot();changes=sorted(set(before)^set(after)|{p for p in before.keys()&after.keys() if before[p]!=after[p]})
result={'status':'PASS' if run.returncode==0 and not changes else 'FAIL','protected_fact_changes':changes,'scope':'Read-only production Live/Data Observation + portfolio-context after patch; does not replace opening production guard','before':before,'after':after}
(OUT/'readonly-after-fix.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(result['status'],changes)
raise SystemExit(0 if result['status']=='PASS' else 1)
