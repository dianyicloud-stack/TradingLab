"""Read-only fingerprint guard proving acceptance never touches the formal Learning DB."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[1]


def fingerprint():
    path=ROOT/'data/learning/learning.db'
    if not path.is_file():return {'exists':False,'path':str(path)}
    result={'exists':True,'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'size':path.stat().st_size}
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
        tables=[row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        result['record_counts']={table:db.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0] for table in tables}
    return result


def main(argv=None):
    parser=argparse.ArgumentParser();group=parser.add_mutually_exclusive_group(required=True);group.add_argument('--capture',type=Path);group.add_argument('--verify',type=Path);args=parser.parse_args(argv);current=fingerprint()
    if args.capture:
        args.capture.parent.mkdir(parents=True,exist_ok=True);args.capture.write_text(json.dumps(current,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'status':'CAPTURED',**current},ensure_ascii=False));return 0
    expected=json.loads(args.verify.read_text(encoding='utf-8'));same=current==expected;print(json.dumps({'status':'PASS' if same else 'FAIL','unchanged':same,'before':expected,'after':current},ensure_ascii=False));return 0 if same else 1


if __name__=='__main__':sys.exit(main())
