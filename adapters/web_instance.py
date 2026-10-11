"""Connect only to the exact live instance holding this data root's lease."""
from pathlib import Path
import json,re,urllib.request

def existing(root,source):
    try:
        record=json.loads((Path(root)/'runtime/web-instance.json').read_text(encoding='utf-8'))
        if record['source']!=source or not re.fullmatch(r'http://127\.0\.0\.1:\d{1,5}',record['url']):return None
        with urllib.request.urlopen(record['url']+'/healthz',timeout=2) as response:value=json.load(response)
        return record['url'] if value.get('instance_id')==record['instance_id'] and value.get('status')=='UP' else None
    except (OSError,ValueError,KeyError):return None

def publish(root,source,server,instance_id):
    from adapters.runtime_platform import identity,build
    from app.system.runtime_state import atomic
    project=Path(__file__).resolve().parents[1]
    path=Path(root)/'runtime/web-instance.json';path.parent.mkdir(parents=True,exist_ok=True)
    atomic(path,{'source':source,'url':f'http://127.0.0.1:{server.server_port}','instance_id':instance_id,
        **identity(),'project':str(project),'data_root':str(Path(root).resolve()),'build':build(project),'token':server.control_token})
