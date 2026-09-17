"""ASGI entry point: ``uvicorn autopricer.asgi:app``.

This is what the container runs. Module-level so a process manager can import
it directly; ``python3 -m autopricer serve`` goes through the same factory.
"""

from __future__ import annotations

from .api import create_app

app = create_app()
