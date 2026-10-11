"""Read-only operational health DTO."""
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class HealthCheck:
    id: str
    name: str
    status: str
    detail: str

    def to_dict(self):
        return asdict(self)
