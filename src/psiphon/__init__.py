"""psiphon — Linux controller for Psiphon (tunnel-core)."""

from importlib.metadata import version
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from psiphon.main import app

__all__ = ["app"]
__version__ = version("psiphon")


def __getattr__(name: str):
    # Keep the worker import independent of the CLI and avoid runpy double imports.
    if name == "app":
        from psiphon.main import app

        return app
    raise AttributeError(name)
