import asyncio
import contextlib
import logging
import threading
from typing import Callable, Dict, List, AsyncGenerator

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from contextlib import asynccontextmanager
import uvicorn

from common.subscription.external_transport.base_producer import BaseProducer


class MultiChannelSSE:
    def __init__(self, host: str = "0.0.0.0", port: int = 8888):
        self.host = host
        self.port = port
        self.channels: Dict[str, Dict] = {}

        self.app = FastAPI(lifespan=self.lifespan)
        self._setup_routes()

        self._server = None
        self._thread = None

    # --------------------------------------------------
    # Lifespan
    # --------------------------------------------------
    @asynccontextmanager
    async def lifespan(self, app: FastAPI):
        try:
            yield
        finally:
            # shutdown: cancel all producer tasks
            for channel in self.channels.values():
                task = channel.get("task")
                if task:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task

    # --------------------------------------------------
    # Add Channel
    # --------------------------------------------------
    def add_channel(self, name: str, producer: BaseProducer):

        if name in self.channels:
            raise ValueError(f"Channel '{name}' already exists")
        else:
            logging.info(f"Adding channel '{name}' to subscription")

        self.channels[name] = {
            "producer": producer,
            "clients": [],
            "task": None,
        }

    # --------------------------------------------------
    # Internal Broadcast
    # --------------------------------------------------
    async def _broadcast(self, channel_name: str, message: str):
        channel = self.channels[channel_name]
        for queue in channel["clients"]:
            await queue.put(message)

    # --------------------------------------------------
    # Start Producer For Channel
    # --------------------------------------------------
    async def _start_producer(self, channel_name: str):
        channel = self.channels[channel_name]

        # Capture the event loop of the server thread
        loop = asyncio.get_running_loop()

        def thread_safe_publish(msg: str):
            loop.call_soon_threadsafe(
                lambda: asyncio.create_task(
                    self._broadcast(channel_name, msg)
                )
            )

        try:
            # Pass thread-safe publisher to producer
            await channel["producer"].run(thread_safe_publish)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logging.exception(f"Producer for {channel_name} crashed: {e}")

    # --------------------------------------------------
    # SSE Consumer
    # --------------------------------------------------
    async def _consumer(self, channel_name: str) -> AsyncGenerator[str, None]:

        if channel_name not in self.channels:
            raise HTTPException(status_code=404, detail="Channel not found")

        queue = asyncio.Queue()
        self.channels[channel_name]["clients"].append(queue)

        # Start producer lazily if not started
        if self.channels[channel_name]["task"] is None:
            task = asyncio.create_task(self._start_producer(channel_name))
            self.channels[channel_name]["task"] = task

        try:
            while True:
                message = await queue.get()
                yield f"data: {message}\n\n"
                await asyncio.sleep(0)
        finally:
            # remove client on disconnect
            self.channels[channel_name]["clients"].remove(queue)

    # --------------------------------------------------
    # Routes
    # --------------------------------------------------
    def _setup_routes(self):

        @self.app.get("/")
        async def index():
            return {"channels": list(self.channels.keys())}

        @self.app.get("/stream/{channel_name}")
        async def stream(channel_name: str):
            return StreamingResponse(
                self._consumer(channel_name),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )

    # --------------------------------------------------
    # Run (background thread safe)
    # --------------------------------------------------
    def run(self):
        logging.info(f"Starting SSE Server on {self.host}:{self.port}")

        config = uvicorn.Config(
            self.app,
            host=self.host,
            port=self.port,
            loop="asyncio",
            log_level="info",
        )

        self._server = uvicorn.Server(config)

        def _run():
            asyncio.run(self._server.serve())

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

    def stop(self):
        if self._server:
            self._server.should_exit = True
        if self._thread:
            self._thread.join()


# --------------------------------------------------
# Example Producers
# --------------------------------------------------

class BTCProducer(BaseProducer):

    async def run(self, publish):
        counter = 0
        while True:
            counter += 1
            await publish(f"BTC tick {counter}")
            await asyncio.sleep(1)


class ETHProducer(BaseProducer):

    async def run(self, publish):
        counter = 0
        while True:
            counter += 1
            await publish(f"ETH tick {counter}")
            await asyncio.sleep(2)


# --------------------------------------------------
# Main
# --------------------------------------------------

if __name__ == "__main__":
    server = MultiChannelSSE()
    server.add_channel("eth", ETHProducer())
    server.add_channel("btc", BTCProducer())
    server.run()
    while True:
        pass