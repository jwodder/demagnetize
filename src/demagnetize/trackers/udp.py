# <https://www.bittorrent.org/beps/bep_0015.html>
from __future__ import annotations
from contextlib import nullcontext
from functools import partial
from random import randint
from socket import AF_INET6
import struct
from time import time
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    ContextManager,
    List,
    Optional,
    TypeVar,
    Union,
)
from anyio import create_connected_udp_socket, fail_after
from anyio.abc import ConnectedUDPSocket, SocketAttribute
import attr
from .base import Tracker, TrackerSession, unpack_peers, unpack_peers6
from ..consts import LEFT, NUMWANT
from ..errors import TrackerError
from ..peer import Peer
from ..util import TRACE, InfoHash, Key, log

if TYPE_CHECKING:
    from ..core import Demagnetizer

T = TypeVar("T")

PROTOCOL_ID = 0x41727101980


@attr.define
class UDPTracker(Tracker):
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
            transaction_id = make_transaction_id()
            conn_id = await self.send_receive(
                build_connection_request(transaction_id),
                partial(parse_connection_response, transaction_id),
            )
            self.connection = Connection(session=self, id=conn_id)
        return self.connection

    def reset_connection(self) -> None:
        self.connection = None

    async def announce(self, info_hash: InfoHash) -> List[Peer]:
        while True:
            conn = await self.get_connection()
            try:
                r = await conn.announce(info_hash)
            except ConnectionTimeoutError:
                log.log(
                    TRACE,
                    "Connection to %s timed out; restarting",
                    self.tracker,
                )
                self.reset_connection()
                continue
            log.info("%s returned %d peers", self.tracker, len(r.peers))
            log.log(
                TRACE,
                "%s returned peers: %s",
                self.tracker,
                ", ".join(map(str, r.peers)),
            )
            return r.peers

    async def send_receive(
        self,
        msg: bytes,
        response_parser: Callable[[bytes], Union[T, ErrorResponse]],
        expiration: Optional[float] = None,
    ) -> T:
        ctx: ContextManager[Any]
        if expiration is None:
            ctx = nullcontext()
        else:
            ctx = fail_after(expiration - time())
        try:
            with ctx:
                n = 0
                while True:
                    log.log(TRACE, "Sending to %s: %r", self.tracker, msg)
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
                    log.log(TRACE, "%s responded with: %r", self.tracker, resp)
                    try:
                        data = response_parser(resp)
                    except Exception as e:
                        log.log(
                            TRACE,
                            "Response from %s was invalid, will resend: %s: %s",
                            self.tracker,
                            type(e).__name__,
                            e,
                        )
                        continue
                    if isinstance(data, ErrorResponse):
                        raise TrackerError(
                            f"{self.tracker} replied with error: {data.message}"
                        )
                    return data
        except TimeoutError:
            raise ConnectionTimeoutError


@attr.define
class Connection:
    session: UDPTrackerSession
    id: int
    expiration: float = attr.field(init=False)

    def __attrs_post_init__(self) -> None:
        self.expiration = time() + 60

    async def announce(self, info_hash: InfoHash) -> AnnounceResponse:
        transaction_id = make_transaction_id()
        msg = build_announce_request(
            transaction_id=transaction_id,
            connection_id=self.id,
            info_hash=info_hash,
            peer_id=self.session.app.peer_id,
            peer_port=self.session.app.peer_port,
            key=self.session.app.key,
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
class ErrorResponse:
    message: str


@attr.define
class AnnounceResponse:
    interval: int
    leechers: int
    seeders: int
    peers: List[Peer]


def make_transaction_id() -> int:
    return randint(-(1 << 31), (1 << 31) - 1)


def build_connection_request(transaction_id: int) -> bytes:
    return struct.pack("!qii", PROTOCOL_ID, 0, transaction_id)


def get_error_response(resp: bytes) -> Optional[ErrorResponse]:
    action, _ = struct.unpack_from("!ii", resp)
    ### TODO: Should we ever care about checking the transaction ID?
    if action == 3:
        msg = resp[8:].decode("utf-8", "replace")
        return ErrorResponse(msg)
    else:
        return None


def parse_connection_response(
    transaction_id: int, resp: bytes
) -> Union[int, ErrorResponse]:
    # Returns connection ID or error
    if (er := get_error_response(resp)) is not None:
        return er
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
    transaction_id: int,
    connection_id: int,
    info_hash: InfoHash,
    peer_id: bytes,
    peer_port: int,
    key: Key,
) -> bytes:
    downloaded = 0
    uploaded = 0
    event = 2
    ip_address = b"\0\0\0\0"
    return (
        struct.pack("!qii", connection_id, 1, transaction_id)
        + bytes(info_hash)
        + (peer_id + b"\0" * 20)[:20]
        + struct.pack("!qqqi", downloaded, LEFT, uploaded, event)
        + ip_address
        + bytes(key)
        + struct.pack("!iH", NUMWANT, peer_port)
    )


def parse_announce_response(
    transaction_id: int, resp: bytes, is_ipv6: bool
) -> Union[AnnounceResponse, ErrorResponse]:
    if (er := get_error_response(resp)) is not None:
        return er
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
    return AnnounceResponse(
        interval=interval, leechers=leechers, seeders=seeders, peers=peers
    )
