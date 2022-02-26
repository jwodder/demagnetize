from __future__ import annotations
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, Optional
from anyio import connect_tcp
from anyio.abc import AsyncResource, SocketStream
from .util import InfoHash, log


@dataclass
class Peer:
    host: str
    port: int
    id: Optional[bytes] = None

    def __str__(self) -> str:
        if ":" in self.host:
            return f"[{self.host}]:{self.port}"
        else:
            return f"{self.host}:{self.port}"

    def for_json(self) -> Dict[str, Any]:
        pid: Optional[str]
        if self.id is not None:
            pid = self.id.decode("utf-8", "replace")
        else:
            pid = None
        return {"host": self.host, "port": self.port, "id": pid}

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[ConnectedPeer]:
        log.debug("Connecting to peer at %s", self)
        async with await connect_tcp(self.host, self.port) as conn:
            log.debug("Connected to peer at %s", self)
            async with ConnectedPeer(conn) as connpeer:
                yield connpeer

    async def get_metadata(self, info_hash: InfoHash) -> dict:
        log.info("Requesting metadata for %s from peer %s", info_hash, self)
        async with self.connect() as connpeer:
            return await connpeer.get_metadata(info_hash)


@dataclass
class ConnectedPeer(AsyncResource):
    conn: SocketStream

    async def aclose(self) -> None:
        await self.conn.aclose()

    async def get_metadata(self, info_hash: InfoHash) -> dict:
        raise NotImplementedError
