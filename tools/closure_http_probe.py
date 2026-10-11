"""Isolated actual HTTP server/Node fetch transport diagnostic. No app/data owner."""
from pathlib import Path
from types import SimpleNamespace
from threading import Thread
import subprocess,sys,json
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.shell.server import make_server
app=SimpleNamespace(routers=());server=make_server(app,0);thread=Thread(target=server.serve_forever,daemon=True);thread.start()
node=Path(__import__('os').environ.get('TRADING_LAB_NODE', str(ROOT/'.dev/runtime/node/node.exe')))
try:
 result=subprocess.run([str(node),str(ROOT/'tools/closure_http_probe.js'),f'http://127.0.0.1:{server.server_port}',str(ROOT/'artifacts/m2_auto_agent_closure/http-probe-diagnostic.json')],timeout=240)
finally:server.shutdown();server.server_close();thread.join(3)
