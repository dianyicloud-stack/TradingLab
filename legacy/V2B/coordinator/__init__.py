"""V2B coordinator core package."""

from .errors import CoordinatorError, ErrorCode

__all__ = ["CoordinatorError", "ErrorCode", "V2BCoordinator"]


def __getattr__(name: str):
    if name == "V2BCoordinator":
        from .service import V2BCoordinator

        return V2BCoordinator
    raise AttributeError(name)
