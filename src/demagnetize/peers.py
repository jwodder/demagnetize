from __future__ import annotations
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator, Optional
from anyio import connect_tcp
from anyio.abc import AsyncResource, SocketStream
from .util import InfoHash, log


@dataclass
class Peer:
    host: str
    port: int
    id: Optional[str] = None

    def __str__(self) -> str:
        if ":" in self.host:
            return f"[{self.host}]:{self.port}"
        else:
            return f"{self.host}:{self.port}"

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[ConnectedPeer]:
        log.debug("Connecting to peer at %s", self)
        async with await connect_tcp(self.host, self.port) as conn:
            log.debug("Connected to peer at %s", self)
            yield ConnectedPeer(conn)

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
