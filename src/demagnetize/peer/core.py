from __future__ import annotations
from typing import TYPE_CHECKING, NoReturn, Optional
from anyio import (
    BrokenResourceError,
    ClosedResourceError,
    EndOfStream,
    IncompleteRead,
    connect_tcp,
    fail_after,
)
from anyio.abc import ObjectStream, SocketStream
from anyio.streams.buffered import BufferedByteReceiveStream
import attr
from .extensions import BEP9MsgType, BEP10Extension, BEP10Registry, Extension
from .messages import (
    AllowedFast,
    AnyMessage,
    BEP9Message,
    Bitfield,
    EmptyMessage,
    ExtendedHandshake,
    Handshake,
    Have,
    HaveNone,
    Piece,
    Suggest,
    decode_message,
    encode_message,
)
from ..bencode import unbencode
from ..consts import CLIENT, MAX_PEER_MSG_LEN, PEER_HANDSHAKE_TIMEOUT, UT_METADATA
from ..errors import PeerError, UnbencodeError
from ..util import TRACE, InfoHash, InfoPiecer, log

if TYPE_CHECKING:
    from ..core import Demagnetizer


SUPPORTED_EXTENSIONS = {Extension.BEP10_EXTENSIONS, Extension.FAST}

LOCAL_BEP10_REGISTRY = BEP10Registry.from_dict(
    {
        BEP10Extension.METADATA: UT_METADATA,
    }
)

IGNORED_MESSAGES = (
    EmptyMessage,
    Have,
    Bitfield,
    Piece,
    AllowedFast,
    Suggest,
    # It's valid for a peer to send an extended handshake more than once, and
    # it's valid for us to ignore subsequent handshakes, so that's what we'll
    # do.
    ExtendedHandshake,
)

PeerAddress = tuple[str, int]


@attr.define
class Peer:
    host: str
    port: int
    id: Optional[bytes] = None  # noqa: A003

    def __str__(self) -> str:
        if ":" in self.host:
            addr = f"[{self.host}]:{self.port}"
        else:
            addr = f"{self.host}:{self.port}"
        return f"<Peer {addr}>"

    @property
    def address(self) -> PeerAddress:
        return (self.host, self.port)

    async def get_info(self, app: Demagnetizer, info_hash: InfoHash) -> dict:
        log.info("Requesting info for %s from %s", info_hash, self)
        try:
            try:
                with fail_after(PEER_HANDSHAKE_TIMEOUT):
                    conn = await self.connect(app, info_hash)
            except TimeoutError:
                raise PeerError(
                    peer=self,
                    info_hash=info_hash,
                    msg="Could not connect to peer in time",
                )
            async with conn:
                return await get_metadata_info(conn)
        except OSError as e:
            raise PeerError(
                peer=self,
                info_hash=info_hash,
                msg=f"Communication error: {type(e).__name__}: {e}",
            )

    async def connect(self, app: Demagnetizer, info_hash: InfoHash) -> PeerConnection:
        log.debug("Connecting to %s", self)
        s = await connect_tcp(self.host, self.port)
        log.log(TRACE, "Connected to %s", self)
        conn = PeerConnection(peer=self, app=app, socket=s, info_hash=info_hash)
        try:
            await conn.handshake()
        except BaseException:
            await conn.aclose()
            raise
        return conn


@attr.define
class PeerConnection(ObjectStream[AnyMessage]):
    peer: Peer
    app: Demagnetizer
    socket: SocketStream
    info_hash: InfoHash
    readstream: BufferedByteReceiveStream = attr.field(init=False)
    extensions: set[Extension] = attr.Factory(set)
    remote_bep10_registry: BEP10Registry = attr.Factory(BEP10Registry)

    def __attrs_post_init__(self) -> None:
        self.readstream = BufferedByteReceiveStream(self.socket)

    async def aclose(self) -> None:
        await self.socket.aclose()

    async def send(self, msg: AnyMessage) -> None:
        log.log(TRACE, "Sending to %s: %s", self.peer, msg)
        try:
            await self.socket.send(encode_message(msg, self.remote_bep10_registry))
        except (BrokenResourceError, ClosedResourceError):
            self.error("Peer closed the connection early")

    async def send_eof(self) -> None:
        await self.socket.send_eof()

    async def read(self, length: int) -> bytes:
        try:
            return await self.readstream.receive_exactly(length)
        except (EndOfStream, IncompleteRead, BrokenResourceError, ClosedResourceError):
            self.error("Peer closed the connection early")

    async def handshake(self) -> None:
        log.log(TRACE, "Sending handshake to %s", self.peer)
        try:
            await self.socket.send(
                bytes(
                    Handshake(
                        extensions=set(SUPPORTED_EXTENSIONS),  # set() for mypy
                        info_hash=self.info_hash,
                        peer_id=self.app.peer_id,
                    )
                )
            )
        except (BrokenResourceError, ClosedResourceError):
            self.error("Peer closed the connection early")
        r = await self.read(Handshake.LENGTH)
        try:
            hs = Handshake.parse(r)
        except ValueError as e:
            log.log(TRACE, "Bad handshake from %s: %r", self.peer, r)
            self.error(f"Peer sent bad handshake: {e}")
        log.log(TRACE, "%s sent %s", self.peer, hs)
        if hs.info_hash != self.info_hash:
            self.error(f"Peer replied with wrong info hash (got {hs.info_hash})")
        self.extensions = SUPPORTED_EXTENSIONS & hs.extensions
        if Extension.BEP10_EXTENSIONS in self.extensions:
            await self.send(
                ExtendedHandshake.make(extensions=LOCAL_BEP10_REGISTRY, client=CLIENT)
            )
        else:
            self.error("Peer does not support BEP 10 extensions")
        if Extension.FAST in self.extensions:
            await self.send(HaveNone())

    def error(self, msg: str) -> NoReturn:
        raise PeerError(peer=self.peer, info_hash=self.info_hash, msg=msg)

    async def receive(self) -> AnyMessage:
        while True:
            blen = await self.read(4)
            length = int.from_bytes(blen, "big")
            if length > MAX_PEER_MSG_LEN:
                self.error(
                    f"Peer tried to send overly large message of {length}"
                    " bytes; not trusting"
                )
            if length == 0:
                log.log(TRACE, "%s sent keepalive", self.peer)
            else:
                payload = await self.read(length)
                try:
                    msg = decode_message(blen + payload, LOCAL_BEP10_REGISTRY)
                except ValueError as e:
                    log.log(TRACE, "Bad message from %s: %r", self.peer, payload)
                    self.error(f"Peer sent invalid message: {e}")
                else:
                    log.log(TRACE, "%s sent message: %s", self.peer, msg)
                    return msg


async def get_metadata_info(conn: PeerConnection) -> dict:
    # Unlike a normal torrent, we expect to get the entire info from a single
    # peer and error if it can't give it to us (because peers should only be
    # sending any info if they've checked the whole thing, and if they can't
    # send it all, why should we trust them?)
    ### TODO: Put a timeout on this:
    async for msg in conn:
        if isinstance(msg, ExtendedHandshake):
            handshake = msg
            break
        elif not isinstance(msg, IGNORED_MESSAGES):
            conn.error(f"Peer sent unexpected message: {msg}")
    conn.remote_bep10_registry = handshake.extensions
    if BEP10Extension.METADATA not in conn.remote_bep10_registry:
        conn.error("Peer does not support metadata transfer")
    if handshake.metadata_size is None:
        conn.error("Peer did not report info size in extended handshake")
    log.log(
        TRACE, "%s declares info size as %d bytes", conn.peer, handshake.metadata_size
    )
    info_piecer = InfoPiecer(handshake.metadata_size)
    for i in range(info_piecer.piece_qty):
        log.debug(
            "Sending request to %s for info piece %d/%d",
            conn.peer,
            i,
            info_piecer.piece_qty,
        )
        await conn.send(BEP9Message(msg_type=BEP9MsgType.REQUEST, piece=i))
        async for msg in conn:
            if isinstance(msg, BEP9Message):
                if msg.msg_type == BEP9MsgType.DATA:
                    if msg.piece != i:
                        conn.error(
                            f"received data for info piece {msg.piece}, which"
                            " we did not request"
                        )
                    elif (
                        msg.total_size is not None
                        and msg.total_size != info_piecer.total_size
                    ):
                        conn.error(
                            "'total_size' in info data message"
                            f" ({msg.total_size}) differs from previous value"
                            f" ({info_piecer.total_size})"
                        )
                    log.debug("%s sent info piece %d", conn.peer, msg.piece)
                    try:
                        info_piecer.add_piece(msg.payload)
                    except ValueError as e:
                        conn.error(f"bad info piece: {e}")
                    break
                elif msg.msg_type == BEP9MsgType.REJECT:
                    conn.error(f"Peer rejected request for info piece {msg.piece}")
                elif msg.msg_type == BEP9MsgType.REQUEST:
                    log.log(
                        TRACE,
                        "%s sent request for info piece %d; rejecting",
                        conn.peer,
                        msg.piece,
                    )
                    await conn.send(
                        BEP9Message(msg_type=BEP9MsgType.REJECT, piece=msg.piece)
                    )
                else:
                    log.log(
                        TRACE,
                        "%s sent ut_metadata message with unknown msg_type %d;"
                        " ignoring",
                        conn.peer,
                        msg.msg_type,
                    )
            elif not isinstance(msg, IGNORED_MESSAGES):
                conn.error(f"Peer sent unexpected message: {msg}")
    log.debug("All info pieces received from %s; validating ...", conn.peer)
    if (good_dgst := conn.info_hash.as_hex) != (dgst := info_piecer.get_digest()):
        conn.error(
            f"Received info with invalid digest; expected {good_dgst}, got {dgst}"
        )
    data = info_piecer.get_data()
    try:
        info = unbencode(data)
    except UnbencodeError as e:
        conn.error(f"Received invalid bencoded data as info: {e}")
    if not isinstance(info, dict):
        conn.error("Received bencoded non-dict as info")
    return info
