"""Read-only source checks; only writes a report, never production configuration."""
from pathlib import Path
from datetime import datetime,timezone
import json,sys,urllib.request
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from adapters.source_configuration import source_configuration
from adapters.market_source_lifecycle import SourceLifecycle
from adapters.baselines import verify_baselines

def main():
    _,config=source_configuration(ROOT,ROOT/'data')
    lifecycle=SourceLifecycle(ROOT,config)
    value={'created_at':datetime.now(timezone.utc).isoformat(),'production_source':config['active_market_source'],
        'configuration':config,'dependencies':lifecycle.inspect(),'baselines':verify_baselines(ROOT),
        'real_ai':'NOT_RUN','old_workspace_required':False,'migration_required':config['migration_required']}
    out=ROOT/'artifacts/market_cutover/real-preflight.json';out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');print(out)
if __name__=='__main__':main()
