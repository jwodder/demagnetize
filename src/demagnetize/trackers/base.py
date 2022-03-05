from __future__ import annotations
from abc import ABC, abstractmethod
from enum import Enum
from ipaddress import AddressValueError, IPv4Address, IPv6Address
import struct
from typing import TYPE_CHECKING, ClassVar
from anyio import fail_after
from anyio.abc import AsyncResource
import attr
from yarl import URL
from ..consts import LEFT, TRACKER_TIMEOUT
from ..errors import TrackerError, TrackerFailure
from ..peer import Peer
from ..util import TRACE, InfoHash, log

if TYPE_CHECKING:
    from ..core import Demagnetizer


@attr.define
class Tracker(ABC):
    SCHEMES: ClassVar[list[str]]
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

    async def get_peers(self, app: Demagnetizer, info_hash: InfoHash) -> list[Peer]:
        log.info("Requesting peers for %s from %s", info_hash, self)
        try:
            with fail_after(TRACKER_TIMEOUT):
                async with await self.connect(app) as conn:
                    peers = (
                        await conn.announce(info_hash, AnnounceEvent.STARTED)
                    ).peers
                    log.info("%s returned %d peers", self, len(peers))
                    log.log(
                        TRACE,
                        "%s returned peers: %s",
                        self,
                        ", ".join(map(str, peers)),
                    )
                    return peers
        except TrackerFailure as e:
            raise TrackerError(
                tracker=self,
                info_hash=info_hash,
                msg=f"Tracker replied with failure: {e}",
            )
        except TimeoutError:
            raise TrackerError(
                tracker=self, info_hash=info_hash, msg="Tracker did not respond in time"
            )
        except OSError as e:
            raise TrackerError(
                tracker=self,
                info_hash=info_hash,
                msg=f"Error communicating with tracker: {type(e).__name__}: {e}",
            )

    @abstractmethod
    async def connect(self, app: Demagnetizer) -> TrackerSession:
        ...


class TrackerSession(AsyncResource):
    @abstractmethod
    async def announce(
        self,
        info_hash: InfoHash,
        event: AnnounceEvent,
        downloaded: int = 0,
        uploaded: int = 0,
        left: int = LEFT,
    ) -> AnnounceResponse:
        ...


class AnnounceEvent(Enum):
    ANNOUNCE = ("", 0)
    COMPLETED = ("completed", 1)
    STARTED = ("started", 2)
    STOPPED = ("stopped", 3)

    def __init__(self, http_value: str, udp_value: int) -> None:
        self.http_value = http_value
        self.udp_value = udp_value


@attr.define
class AnnounceResponse:
    interval: int
    peers: list[Peer]


def unpack_peers(data: bytes) -> list[Peer]:
    peers: list[Peer] = []
    try:
        for (ipnum, port) in struct.iter_unpack("!IH", data):
            ip = str(IPv4Address(ipnum))
            peers.append(Peer(host=ip, port=port))
    except (struct.error, AddressValueError):
        raise ValueError("invalid 'peers' list")
    return peers


def unpack_peers6(data: bytes) -> list[Peer]:
    peers6: list[Peer] = []
    try:
        for (*ipbytes, port) in struct.iter_unpack("!16cH", data):
            ip = str(IPv6Address(b"".join(ipbytes)))
            peers6.append(Peer(host=ip, port=port))
    except (struct.error, AddressValueError):
        raise ValueError("invalid 'peers6' list")
    return peers6
