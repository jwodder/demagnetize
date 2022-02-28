from __future__ import annotations
from abc import ABC, abstractmethod
from ipaddress import AddressValueError, IPv4Address, IPv6Address
import struct
from typing import TYPE_CHECKING, List
from anyio.abc import AsyncResource
import attr
from yarl import URL
from ..peer import Peer
from ..util import InfoHash

if TYPE_CHECKING:
    from ..core import Demagnetizer


@attr.define
class Tracker(ABC):
    url: URL

    def __str__(self) -> str:
        return f"<Tracker {self.url}>"

    async def get_peers(self, app: Demagnetizer, info_hash: InfoHash) -> List[Peer]:
        async with await self.connect(app) as conn:
            return await conn.announce(info_hash)

    @abstractmethod
    async def connect(self, app: Demagnetizer) -> TrackerSession:
        ...


class TrackerSession(AsyncResource):
    @abstractmethod
    async def announce(self, info_hash: InfoHash) -> List[Peer]:
        ...


def unpack_peers(data: bytes) -> List[Peer]:
    peers: List[Peer] = []
    try:
        for (ipnum, port) in struct.iter_unpack("!IH", data):
            ip = str(IPv4Address(ipnum))
            peers.append(Peer(host=ip, port=port))
    except (struct.error, AddressValueError):
        raise ValueError("invalid 'peers' list")
    return peers


def unpack_peers6(data: bytes) -> List[Peer]:
    peers6: List[Peer] = []
    try:
        for (*ipbytes, port) in struct.iter_unpack("!16cH", data):
            ip = str(IPv6Address(b"".join(ipbytes)))
            peers6.append(Peer(host=ip, port=port))
    except (struct.error, AddressValueError):
        raise ValueError("invalid 'peers6' list")
    return peers6
