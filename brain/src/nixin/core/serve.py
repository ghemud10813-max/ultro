"""Run uvicorn servers inside the brain's own asyncio loop."""

from __future__ import annotations

import asyncio
import logging

import uvicorn


class EmbeddedServer:
    def __init__(self, app, host: str, port: int, certfile: str | None = None, keyfile: str | None = None,
                 ws_max_size: int = 8 * 1024 * 1024) -> None:
        config = uvicorn.Config(
            app,
            host=host,
            port=port,
            ssl_certfile=certfile,
            ssl_keyfile=keyfile,
            log_level="warning",
            ws_max_size=ws_max_size,
            ws_ping_interval=20,
            ws_ping_timeout=40,
            lifespan="off",
            access_log=False,
        )
        self.server = uvicorn.Server(config)
        # We manage signals ourselves (Ctrl+C in the CLI).
        self.server.install_signal_handlers = lambda: None  # type: ignore[method-assign]
        self.task: asyncio.Task | None = None

    @property
    def port(self) -> int:
        """Actual bound port (useful when started with port=0)."""
        for s in self.server.servers:
            for sock in s.sockets:
                return sock.getsockname()[1]
        return self.server.config.port

    async def start(self, timeout: float = 10.0) -> None:
        self.task = asyncio.create_task(self.server.serve())
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while not self.server.started:
            if self.task.done():
                exc = self.task.exception()
                raise RuntimeError(f"Server failed to start on {self.server.config.host}:{self.server.config.port}: {exc}")
            if loop.time() > deadline:
                raise TimeoutError("Server did not start in time")
            await asyncio.sleep(0.02)

    async def stop(self) -> None:
        self.server.should_exit = True
        if self.task:
            try:
                await asyncio.wait_for(self.task, 5)
            except (TimeoutError, asyncio.CancelledError):
                self.task.cancel()


logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
