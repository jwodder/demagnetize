from __future__ import annotations
from abc import ABC, abstractmethod
from enum import Enum
from ipaddress import AddressValueError, IPv4Address, IPv6Address
import struct
from typing import TYPE_CHECKING, ClassVar
from anyio import fail_after
from anyio.abc import AsyncResource
from anyio.streams.memory import MemoryObjectSendStream
import attr
from yarl import URL
from ..consts import LEFT, TRACKER_STOP_TIMEOUT, TRACKER_TIMEOUT
from ..errors import TrackerError, TrackerFailure
from ..peer import Peer
from ..util import TRACE, InfoHash, log

if TYPE_CHECKING:
    from ..core import Demagnetizer


# NOTE: Avoid using slotted classes here, as combining them with attrs and
# `__subclasses__` can lead to Heisenbugs depending on when garbage collection
# happens.
@attr.define(slots=False)
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

    async def get_peers(
        self,
        app: Demagnetizer,
        info_hash: InfoHash,
        sender: MemoryObjectSendStream[Peer],
    ) -> None:
        log.info("Requesting peers for %s from %s", info_hash, self)
        try:
            with fail_after(TRACKER_TIMEOUT):
                async with sender, await self.connect(app) as conn:
                    log.log(
                        TRACE,
                        "Sending 'started' announcement to %s for %s",
                        self,
                        info_hash,
                    )
                    peers = (
                        await conn.announce(info_hash, AnnounceEvent.STARTED)
                    ).peers
                    log.info("%s returned %d peers for %s", self, len(peers), info_hash)
                    log.debug(
                        "%s returned peers for %s: %s",
                        self,
                        info_hash,
                        ", ".join(map(str, peers)) or "<none>",
                    )
                    for p in peers:
                        await sender.send(p)
                    with fail_after(TRACKER_STOP_TIMEOUT, shield=True):
                        log.log(
                            TRACE,
                            "Sending 'stopped' announcement to %s for %s",
                            self,
                            info_hash,
                        )
                        await conn.announce(info_hash, AnnounceEvent.STOPPED)
        except TrackerError as e:
            log.warning(
                "Error getting peers for %s from %s: %s", info_hash, self, e.msg
            )
        except TrackerFailure as e:
            log.warning(
                "%s replied to announcement for %s with failure message: %s",
                self,
                info_hash,
                e,
            )
        except TimeoutError:
            log.warning("%s did not respond in time", self)
        except OSError as e:
            log.warning(
                "Error communicating with %s: %s: %s", self, type(e).__name__, e
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
        for ipnum, port in struct.iter_unpack("!IH", data):
            ip = str(IPv4Address(ipnum))
            peers.append(Peer(host=ip, port=port))
    except (struct.error, AddressValueError):
        raise ValueError("invalid 'peers' list")
    return peers


def unpack_peers6(data: bytes) -> list[Peer]:
    peers6: list[Peer] = []
    try:
        for *ipbytes, port in struct.iter_unpack("!16cH", data):
            ip = str(IPv6Address(b"".join(ipbytes)))
            peers6.append(Peer(host=ip, port=port))
    except (struct.error, AddressValueError):
        raise ValueError("invalid 'peers6' list")
    return peers6
