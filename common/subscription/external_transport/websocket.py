import asyncio
import contextlib
import logging
import threading
from typing import Callable, Dict, List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from contextlib import asynccontextmanager
import uvicorn

from common.config_logging import to_stdout_and_file, to_stdout
from common.subscription.external_transport.base_producer import BaseProducer


class MultiChannelWebSocket:
    def __init__(self, host: str = "0.0.0.0", port: int = 8888,default_route_name: str = "stream"):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.host = host
        self.port = port
        self.channels: Dict[str, Dict] = {}
        self.default_route_name = default_route_name
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
            self.logger.info(f"Adding channel '{name}'")

        self.channels[name] = {
            "producer": producer,
            "clients": [],
            "task": None,
        }

    # --------------------------------------------------
    # Broadcast
    # --------------------------------------------------
    async def _broadcast(self, channel_name: str, message: str):

        channel = self.channels[channel_name]

        disconnected = []

        for ws in channel["clients"]:
            try:
                await ws.send_text(message)
            except Exception:
                disconnected.append(ws)

        for ws in disconnected:
            channel["clients"].remove(ws)

    # --------------------------------------------------
    # Producer
    # --------------------------------------------------
    async def _start_producer(self, channel_name: str):

        channel = self.channels[channel_name]
        loop = asyncio.get_running_loop()

        def thread_safe_publish(msg: str):
            loop.call_soon_threadsafe(
                lambda: asyncio.create_task(
                    self._broadcast(channel_name, msg)
                )
            )

        try:
            await channel["producer"].run(thread_safe_publish)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logging.exception(f"Producer for {channel_name} crashed: {e}")

    # --------------------------------------------------
    # WebSocket Handler
    # --------------------------------------------------
    async def _ws_handler(self, websocket: WebSocket, channel_name: str):

        if channel_name not in self.channels:
            raise HTTPException(status_code=404, detail="Channel not found")

        await websocket.accept()

        channel = self.channels[channel_name]
        channel["clients"].append(websocket)

        # Lazy start producer
        if channel["task"] is None:
            channel["task"] = asyncio.create_task(
                self._start_producer(channel_name)
            )

        try:
            while True:
                # wait for client messages (optional)
                await websocket.receive_text()

        except WebSocketDisconnect:
            pass

        finally:
            if websocket in channel["clients"]:
                channel["clients"].remove(websocket)

    # --------------------------------------------------
    # Routes
    # --------------------------------------------------
    def _setup_routes(self):

        @self.app.get("/")
        async def index():
            return {"channels": list(self.channels.keys())}

        @self.app.websocket("/"+self.default_route_name+"/{channel_name}")
        async def websocket_endpoint(websocket: WebSocket, channel_name: str):
            await self._ws_handler(websocket, channel_name)

    # --------------------------------------------------
    # Run
    # --------------------------------------------------
    def run(self):

        self.logger.info(f"Starting WebSocket Server on {self.host}:{self.port}")

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

class BTCProducer(BaseProducer):

    async def run(self, publish):
        counter = 0
        while True:
            counter += 1
            publish(f"BTC tick {counter}")
            await asyncio.sleep(1)


class ETHProducer(BaseProducer):

    async def run(self, publish):
        counter = 0
        while True:
            counter += 1
            publish(f"ETH tick {counter}")
            await asyncio.sleep(2)

if __name__ == "__main__":
    to_stdout()
    server = MultiChannelWebSocket()

    server.add_channel("btc", BTCProducer())
    server.add_channel("eth", ETHProducer())

    server.run()
    while True:
        pass