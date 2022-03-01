from __future__ import annotations
from abc import ABC, abstractmethod
from ipaddress import AddressValueError, IPv4Address, IPv6Address
import struct
from typing import TYPE_CHECKING, ClassVar, List
from anyio.abc import AsyncResource
import attr
from yarl import URL
from ..peer import Peer
from ..util import InfoHash, log

if TYPE_CHECKING:
    from ..core import Demagnetizer


@attr.define
class Tracker(ABC):
    SCHEMES: ClassVar[List[str]]
    url: URL

    def __str__(self) -> str:
        return f"<Tracker {self.url}>"

    @classmethod
    def from_url(cls, url: str) -> Tracker:
        u = URL(url)  # Raises ValueError on failure
        for klass in Tracker.__subclasses__():
            if u.scheme in klass.SCHEMES:
                return klass(url=u)  # type: ignore[abstract]
        raise ValueError(f"Unsupported tracker URL scheme {u.scheme!r}")

    async def get_peers(self, app: Demagnetizer, info_hash: InfoHash) -> List[Peer]:
        log.info("Requesting peers for %s from %s", info_hash, self)
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
