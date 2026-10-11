"""Presentation contracts and registration. No domain behavior."""
from dataclasses import dataclass
import re
from typing import Callable
from contracts.system import HealthCheck


@dataclass(frozen=True)
class Page:
    summary: str
    cards: tuple[tuple[str, str], ...]
    rows: tuple[tuple[str, str, str], ...] = ()
    note: str = ""
    # Trusted module-owned templates only; user data is rendered via textContent.
    content_html: str = ""
    styles: tuple[str, ...] = ()
    scripts: tuple[str, ...] = ()


@dataclass(frozen=True)
class Module:
    id: str
    name: str
    route: str
    subtitle: str
    health: Callable[[], HealthCheck]
    page: Callable[[], Page]
    enabled: bool = True

    def declaration(self):
        return {"id": self.id, "name": self.name, "route": self.route,
                "enabled": self.enabled, "health": self.health().to_dict()}


class ModuleRegistry:
    def __init__(self, modules=()):
        self._modules = {}
        for module in modules:
            self.register(module)

    def register(self, module: Module):
        if not re.fullmatch(r"[a-z][a-z0-9_-]*", module.id) or not re.fullmatch(r"/[a-z][a-z0-9_-]*", module.route):
            raise ValueError("Module ID and route must be simple slugs")
        if module.route in {"/api", "/assets", "/healthz"}:
            raise ValueError("Reserved shell route")
        if module.id in self._modules or any(m.route == module.route for m in self._modules.values()):
            raise ValueError("Duplicate module ID or route")
        self._modules[module.id] = module

    @property
    def modules(self):
        return tuple(self._modules.values())

    def resolve(self, route: str):
        return next((m for m in self.modules if m.enabled and m.route == route), None)
