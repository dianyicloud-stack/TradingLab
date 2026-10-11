"""Diagnostic logging only; no business payloads or credentials."""
import logging


def configure_logging():
    import os
    from pathlib import Path
    from logging.handlers import RotatingFileHandler
    handlers=None;service=os.environ.get('TRADING_LAB_MANAGED_SERVICE')
    if service in ('web','agent','supervisor'):
        path=Path(os.environ['TRADING_LAB_DATA_ROOT'])/'runtime/service-logs'/f'{service}.log';path.parent.mkdir(parents=True,exist_ok=True)
        handlers=[RotatingFileHandler(path,maxBytes=512*1024,backupCount=2,encoding='utf-8')]
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(name)s %(message)s",handlers=handlers)
