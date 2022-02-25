from __future__ import annotations
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator, Optional
from anyio import connect_tcp
from anyio.abc import AsyncResource, SocketStream


@dataclass
class Peer:
    host: str
    port: int
    id: Optional[str] = None

    ### TODO: Add a __str__

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[ConnectedPeer]:
        async with await connect_tcp(self.host, self.port) as conn:
            yield ConnectedPeer(conn)


@dataclass
class ConnectedPeer(AsyncResource):
    conn: SocketStream

    async def aclose(self) -> None:
        await self.conn.aclose()

    async def get_metadata(self, info_hash: bytes) -> dict:
        raise NotImplementedError
