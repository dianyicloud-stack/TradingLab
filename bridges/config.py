"""Composition-only local transport configuration; independent of working directory."""
from dataclasses import dataclass
import os
import sys
from pathlib import Path
from dotenv import dotenv_values
import yaml


@dataclass(frozen=True)
class LiveConfig:
    interval_seconds: float = 5

    @classmethod
    def load(cls, project_root, environment=None, *, platform=None):
        root = Path(project_root).resolve()
        env = {**dotenv_values(root/'.env'),**(os.environ if environment is None else environment)}
        config = root/'config/live.yaml'
        values = yaml.safe_load(config.read_text(encoding='utf-8')) if config.is_file() else {}
        values = values or {}
        if not isinstance(values,dict):
            raise ValueError('Invalid Live configuration')
        interval = float(env.get('TRADING_LAB_WATCHER_INTERVAL',values.get('interval_seconds',5)))
        if not 1 <= interval <= 3600:
            raise ValueError('Invalid Live configuration')
        return cls(interval)
