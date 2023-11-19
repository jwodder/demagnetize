# <https://www.bittorrent.org/beps/bep_0015.html>
from __future__ import annotations
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from functools import partial
from random import randint
from socket import AF_INET6
import struct
from time import time
from typing import TYPE_CHECKING, Any, ClassVar, Optional, TypeVar
from anyio import create_connected_udp_socket, fail_after
from anyio.abc import ConnectedUDPSocket, SocketAttribute
import attr
from .base import (
    AnnounceEvent,
    AnnounceResponse,
    Tracker,
    TrackerSession,
    unpack_peers,
    unpack_peers6,
)
from ..consts import LEFT, NUMWANT
from ..errors import TrackerFailure
from ..util import TRACE, InfoHash, Key, log

if TYPE_CHECKING:
    from ..core import Demagnetizer

T = TypeVar("T")

PROTOCOL_ID = 0x41727101980


@attr.define(slots=False)
class UDPTracker(Tracker):
    SCHEMES: ClassVar[list[str]] = ["udp"]

    host: str = attr.field(init=False)
    port: int = attr.field(init=False)

    def __attrs_post_init__(self) -> None:
        if self.url.scheme != "udp":
            raise ValueError("URL scheme must be 'udp'")
        if self.url.host is None:
            raise ValueError("URL missing host")
        if self.url.port is None:
            raise ValueError("URL missing port")
        self.host = self.url.host
        self.port = self.url.port

    async def connect(self, app: Demagnetizer) -> UDPTrackerSession:
        log.debug("Creating UDP socket to host %r, port %r", self.host, self.port)
        s = await create_connected_udp_socket(self.host, self.port)
        return UDPTrackerSession(tracker=self, app=app, socket=s)


@attr.define
class UDPTrackerSession(TrackerSession):
    tracker: UDPTracker
    app: Demagnetizer
    socket: ConnectedUDPSocket
    connection: Optional[Connection] = None

    @property
    def is_ipv6(self) -> bool:
        return self.socket.extra(SocketAttribute.family) == AF_INET6

    async def aclose(self) -> None:
        await self.socket.aclose()

    async def get_connection(self) -> Connection:
        if self.connection is None:
            log.log(TRACE, "Sending connection request to %s", self.tracker)
            transaction_id = make_transaction_id()
            conn_id = await self.send_receive(
                build_connection_request(transaction_id),
                partial(parse_connection_response, transaction_id),
            )
            self.connection = Connection(session=self, id=conn_id)
        return self.connection

    def reset_connection(self) -> None:
        self.connection = None

    async def announce(
        self,
        info_hash: InfoHash,
        event: AnnounceEvent,
        downloaded: int = 0,
        uploaded: int = 0,
        left: int = LEFT,
    ) -> UDPAnnounceResponse:
        while True:
            conn = await self.get_connection()
            try:
                return await conn.announce(
                    info_hash,
                    event,
                    downloaded=downloaded,
                    uploaded=uploaded,
                    left=left,
                    urldata=self.tracker.url.path_qs,
                )
            except ConnectionTimeoutError:
                log.log(
                    TRACE,
                    "Connection to %s timed out; restarting",
                    self.tracker,
                )
                self.reset_connection()

    async def send_receive(
        self,
        msg: bytes,
        response_parser: Callable[[bytes], T],
        expiration: Optional[float] = None,
    ) -> T:
        ctx: AbstractContextManager[Any]
        if expiration is None:
            ctx = nullcontext()
        else:
            ctx = fail_after(expiration - time())
        try:
            with ctx:
                n = 0
                while True:
                    await self.socket.send(msg)
                    try:
                        with fail_after(15 << n):
                            resp = await self.socket.receive()
                    except TimeoutError:
                        log.log(
                            TRACE,
                            "%s did not reply in time; resending message",
                            self.tracker,
                        )
                        if n < 8:
                            ### TODO: Should this count remember timeouts from
                            ### previous connections & connection attempts?
                            n += 1
                        continue
                    try:
                        data = response_parser(resp)
                    except TrackerFailure:
                        raise
                    except Exception as e:
                        log.log(TRACE, "Bad response from %s: %r", self.tracker, resp)
                        log.log(
                            TRACE,
                            "Response from %s was invalid, will resend: %s: %s",
                            self.tracker,
                            type(e).__name__,
                            e,
                        )
                        continue
                    return data
        except TimeoutError:
            raise ConnectionTimeoutError


@attr.define
class Connection:
    session: UDPTrackerSession
    id: int  # noqa: A003
    expiration: float = attr.field(init=False)

    def __attrs_post_init__(self) -> None:
        self.expiration = time() + 60

    async def announce(
        self,
        info_hash: InfoHash,
        event: AnnounceEvent,
        *,
        downloaded: int = 0,
        uploaded: int = 0,
        left: int = LEFT,
        urldata: str,
    ) -> UDPAnnounceResponse:
        transaction_id = make_transaction_id()
        msg = build_announce_request(
            transaction_id=transaction_id,
            connection_id=self.id,
            info_hash=info_hash,
            peer_id=self.session.app.peer_id,
            peer_port=self.session.app.peer_port,
            key=self.session.app.key,
            event=event,
            downloaded=downloaded,
            uploaded=uploaded,
            left=left,
            urldata=urldata,
        )
        return await self.session.send_receive(
            msg,
            partial(
                parse_announce_response,
                transaction_id,
                is_ipv6=self.session.is_ipv6,
            ),
            expiration=self.expiration,
        )


class ConnectionTimeoutError(Exception):
    pass


@attr.define
class UDPAnnounceResponse(AnnounceResponse):
    leechers: int
    seeders: int


def make_transaction_id() -> int:
    return randint(-(1 << 31), (1 << 31) - 1)


def build_connection_request(transaction_id: int) -> bytes:
    return struct.pack("!qii", PROTOCOL_ID, 0, transaction_id)


def raise_error_response(resp: bytes) -> None:
    action, _ = struct.unpack_from("!ii", resp)
    ### TODO: Should we ever care about checking the transaction ID?
    if action == 3:
        msg = resp[8:].decode("utf-8", "replace")
        raise TrackerFailure(msg)


def parse_connection_response(transaction_id: int, resp: bytes) -> int:
    # Returns connection ID or raises error
    raise_error_response(resp)
    action, xaction_id, connection_id = struct.unpack_from("!iiq", resp)
    # Use `struct.unpack_from()` instead of `unpack()` because "Clients ...
    # should not assume packets to be of a certain size"
    if xaction_id != transaction_id:
        raise ValueError(
            f"Transaction ID mismatch: expected {transaction_id}, got {xaction_id}"
        )
    if action != 0:
        raise ValueError(f"Action mismatch: expected 0, got {action}")
    assert isinstance(connection_id, int)
    return connection_id


def build_announce_request(
    *,
    transaction_id: int,
    connection_id: int,
    info_hash: InfoHash,
    peer_id: bytes,
    peer_port: int,
    key: Key,
    event: AnnounceEvent,
    downloaded: int,
    uploaded: int,
    left: int,
    urldata: str,
    numwant: int = NUMWANT,
) -> bytes:
    ip_address = b"\0\0\0\0"
    bs = (
        struct.pack("!qii", connection_id, 1, transaction_id)
        + bytes(info_hash)
        + (peer_id + b"\0" * 20)[:20]
        + struct.pack("!qqqi", downloaded, left, uploaded, event.udp_value)
        + ip_address
        + bytes(key)
        + struct.pack("!iH", numwant, peer_port)
    )
    # BEP 41
    ud = urldata.encode("utf-8")
    while ud:
        segment = ud[:255]
        ud = ud[255:]
        bs += bytes([0x02, len(segment)]) + segment
    return bs


def parse_announce_response(
    transaction_id: int, resp: bytes, is_ipv6: bool
) -> UDPAnnounceResponse:
    raise_error_response(resp)
    header = struct.Struct("!iiiii")
    action, xaction_id, interval, leechers, seeders = header.unpack_from(resp)
    if xaction_id != transaction_id:
        raise ValueError(
            f"Transaction ID mismatch: expected {transaction_id}, got {xaction_id}"
        )
    if action != 1:
        raise ValueError(f"Action mismatch: expected 1, got {action}")
    resp = resp[header.size :]
    if is_ipv6:
        peers = unpack_peers6(resp)
    else:
        peers = unpack_peers(resp)
    return UDPAnnounceResponse(
        interval=interval, leechers=leechers, seeders=seeders, peers=peers
    )
