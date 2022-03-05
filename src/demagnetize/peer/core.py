from __future__ import annotations
from contextlib import asynccontextmanager
import sys
from typing import TYPE_CHECKING, Any, AsyncIterator, NoReturn, Optional, Tuple
from anyio import (
    BrokenResourceError,
    CancelScope,
    ClosedResourceError,
    EndOfStream,
    IncompleteRead,
    connect_tcp,
    create_memory_object_stream,
    create_task_group,
    fail_after,
    sleep,
)
from anyio.abc import AsyncResource, SocketStream, TaskGroup
from anyio.streams.buffered import BufferedByteReceiveStream
import attr
from morecontext import additem
from .extensions import BEP9MsgType, BEP10Extension, BEP10Registry, Extension
from .messages import (
    BEP9Message,
    Extended,
    ExtendedHandshake,
    Handshake,
    HaveNone,
    Message,
)
from .subscribers import (
    ExtendedHandshakeSubscriber,
    ExtendedMessageChanneller,
    MessageSink,
    Subscriber,
)
from ..bencode import unbencode
from ..consts import (
    CLIENT,
    KEEPALIVE_PERIOD,
    MAX_PEER_MSG_LEN,
    PEER_CONNECT_TIMEOUT,
    UT_METADATA,
)
from ..errors import CellClosedError, PeerError, UnbencodeError, UnknownBEP9MsgType
from ..util import TRACE, AsyncCell, InfoHash, InfoPiecer, log

if sys.version_info >= (3, 10):
    from contextlib import aclosing
else:
    from async_generator import aclosing

if TYPE_CHECKING:
    from ..core import Demagnetizer


SUPPORTED_EXTENSIONS = {Extension.BEP10_EXTENSIONS, Extension.FAST}

BEP10_EXTENSIONS = BEP10Registry()
BEP10_EXTENSIONS.register(BEP10Extension.METADATA, UT_METADATA)

PeerAddress = Tuple[str, int]  # Can't be written as "tuple[str, int]" in 3.8


@attr.define
class Peer:
    host: str
    port: int
    id: Optional[bytes] = None

    def __str__(self) -> str:
        if ":" in self.host:
            addr = f"[{self.host}]:{self.port}"
        else:
            addr = f"{self.host}:{self.port}"
        return f"<Peer {addr}>"

    @property
    def address(self) -> PeerAddress:
        return (self.host, self.port)

    def for_json(self) -> dict[str, Any]:
        pid: Optional[str]
        if self.id is not None:
            pid = self.id.decode("utf-8", "replace")
        else:
            pid = None
        return {"host": self.host, "port": self.port, "id": pid}

    async def get_info(self, app: Demagnetizer, info_hash: InfoHash) -> dict:
        log.info("Requesting info for %s from %s", info_hash, self)
        try:
            async with self.connect(app, info_hash) as connpeer:
                return await connpeer.get_info()
        except OSError as e:
            raise PeerError(
                peer=self,
                info_hash=info_hash,
                msg=f"Communication error: {type(e).__name__}: {e}",
            )

    @asynccontextmanager
    async def connect(
        self, app: Demagnetizer, info_hash: InfoHash
    ) -> AsyncIterator[PeerConnection]:
        log.debug("Connecting to %s", self)
        try:
            with fail_after(PEER_CONNECT_TIMEOUT):
                s = await connect_tcp(self.host, self.port)
        except TimeoutError:
            raise PeerError(
                peer=self,
                info_hash=info_hash,
                msg="Could not connect to peer in time",
            )
        async with s:
            log.debug("Connected to %s", self)
            async with create_task_group() as tg:
                async with PeerConnection(
                    peer=self, app=app, socket=s, info_hash=info_hash, task_group=tg
                ) as conn:
                    await conn.handshake()
                    conn.start_tasks()
                    yield conn


@attr.define
class PeerConnection(AsyncResource):
    peer: Peer
    app: Demagnetizer
    socket: SocketStream
    info_hash: InfoHash
    task_group: TaskGroup
    extensions: set[Extension] = attr.Factory(set)
    bep10_handshake: AsyncCell[ExtendedHandshake] = attr.Factory(AsyncCell)
    subscribers: list[Subscriber] = attr.Factory(list)
    readstream: BufferedByteReceiveStream = attr.field(init=False)

    def __attrs_post_init__(self) -> None:
        self.readstream = BufferedByteReceiveStream(self.socket)

    async def aclose(self) -> None:
        with CancelScope(shield=True):
            for s in self.subscribers:
                await s.aclose()
            self.task_group.cancel_scope.cancel()

    async def send(self, msg: Message) -> None:
        log.log(TRACE, "Sending to %s: %s", self.peer, msg)
        await self.socket.send(bytes(msg))

    async def read(self, length: int) -> bytes:
        try:
            return await self.readstream.receive_exactly(length)
        except (EndOfStream, IncompleteRead, BrokenResourceError, ClosedResourceError):
            self.error("Peer closed the connection early")

    async def handshake(self) -> None:
        log.log(TRACE, "Sending handshake to %s", self.peer)
        await self.socket.send(
            bytes(
                Handshake(
                    extensions=set(SUPPORTED_EXTENSIONS),  # set() for mypy
                    info_hash=self.info_hash,
                    peer_id=self.app.peer_id,
                )
            )
        )
        r = await self.read(Handshake.LENGTH)
        try:
            hs = Handshake.parse(r)
        except ValueError as e:
            log.log(TRACE, "Bad handshake from %s: %r", self.peer, r)
            self.error(f"Peer sent bad handshake: {e}")
        extnames: list[str] = []
        for ext in sorted(hs.extensions):
            try:
                extnames.append(Extension(ext).name)
            except ValueError:
                extnames.append(str(ext))
        log.debug(
            "%s sent handshake: extensions=%s, peer_id=%s",
            self.peer,
            " | ".join(extnames) or "<none>",
            hs.peer_id.decode("utf-8", "replace"),
        )
        if hs.info_hash != self.info_hash:
            self.error(f"Peer replied with wrong info hash (got {hs.info_hash})")
        self.extensions = SUPPORTED_EXTENSIONS & hs.extensions
        if Extension.BEP10_EXTENSIONS in self.extensions:
            self.subscribers.append(ExtendedHandshakeSubscriber(self))
            handshake = ExtendedHandshake.make(
                extensions=BEP10_EXTENSIONS, client=CLIENT
            )
            await self.send(handshake.compose())
        else:
            self.error("Peer does not support BEP 10 extensions")
        if Extension.FAST in self.extensions:
            await self.send(HaveNone())

    def error(self, msg: str) -> NoReturn:
        raise PeerError(peer=self.peer, info_hash=self.info_hash, msg=msg)

    def start_tasks(self) -> None:
        self.subscribers.append(MessageSink())
        self.task_group.start_soon(self.handle_messages)
        self.task_group.start_soon(self.send_keepalives)

    async def aiter_messages(self) -> AsyncIterator[Message]:
        while True:
            try:
                blen = await self.read(4)
            except PeerError:
                return
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
                msg = Message.parse(blen + payload)
            except ValueError as e:
                log.log(TRACE, "Bad message from %s: %r", self.peer, payload)
                self.error(f"Peer sent invalid message: {e}")
            yield msg

    async def handle_messages(self) -> None:
        async with aclosing(self.aiter_messages()) as ait:
            async for msg in ait:
                log.log(TRACE, "%s sent message: %s", self.peer, msg)
                notified = False
                for s in list(self.subscribers):
                    if s.match(msg):
                        await s.notify(msg)
                        notified = True
                if not notified:
                    self.error(f"Peer sent unexpected message: {msg}")

    async def send_keepalives(self) -> None:
        while True:
            await sleep(KEEPALIVE_PERIOD)
            log.log(TRACE, "Sending keepalive to %s", self.peer)
            await self.socket.send(b"\0\0\0\0")

    async def get_info(self) -> dict:
        # Unlike a normal torrent, we expect to get the entire info from a
        # single peer and error if it can't give it to us (because peers should
        # only be sending any info if they've checked the whole thing, and if
        # they can't send it all, why should we trust them?)
        try:
            ### TODO: Put a timeout on this:
            handshake = await self.bep10_handshake.get()
        except CellClosedError:
            self.error("Abandoned connection")
        if BEP10Extension.METADATA not in handshake.extensions:
            self.error("Peer does not support metadata transfer")
        if handshake.metadata_size is None:
            self.error("Peer did not report info size in extended handshake")
        log.debug(
            "%s declares info size as %d bytes", self.peer, handshake.metadata_size
        )
        info_piecer = InfoPiecer(handshake.metadata_size)
        sender, receiver = create_memory_object_stream(0, Extended)
        async with sender, receiver:
            channeller = ExtendedMessageChanneller(UT_METADATA, sender)
            with additem(self.subscribers, channeller):
                for i in range(info_piecer.piece_qty):
                    log.debug(
                        "Sending request to %s for info piece %d/%d",
                        self.peer,
                        i,
                        info_piecer.piece_qty,
                    )
                    md_msg = BEP9Message(msg_type=BEP9MsgType.REQUEST, piece=i)
                    await self.send(
                        md_msg.compose(
                            handshake.extensions.to_code[BEP10Extension.METADATA]
                        )
                    )
                    async for msg in receiver:
                        try:
                            bm = BEP9Message.parse(msg.payload)
                        except UnknownBEP9MsgType as e:
                            log.log(
                                TRACE,
                                "%s sent ut_metadata message with unknown"
                                " msg_type %d; ignoring",
                                self.peer,
                                e.msg_type,
                            )
                            continue
                        except ValueError as e:
                            self.error(f"received invalid ut_metadata message: {e}")
                        if bm.msg_type is BEP9MsgType.DATA:
                            if bm.piece != i:
                                self.error(
                                    "received data for info piece"
                                    f" {bm.piece}, which we did not request"
                                )
                            elif (
                                bm.total_size is not None
                                and bm.total_size != info_piecer.total_size
                            ):
                                self.error(
                                    "'total_size' in info data message"
                                    f" ({bm.total_size}) differs from"
                                    f" previous value ({info_piecer.total_size})"
                                )
                            log.debug("%s sent info piece %d", self.peer, bm.piece)
                            try:
                                info_piecer.add_piece(bm.payload)
                            except ValueError as e:
                                self.error(f"bad info piece: {e}")
                            break
                        elif bm.msg_type is BEP9MsgType.REJECT:
                            if bm.piece != i:
                                self.error(
                                    "received reject for info piece"
                                    f" {bm.piece}, which we did not request"
                                )
                            log.debug(
                                "%s rejected request for info piece %d",
                                self.peer,
                                bm.piece,
                            )
                        elif bm.msg_type is BEP9MsgType.REQUEST:
                            log.log(
                                TRACE,
                                "%s sent request for info piece %d; rejecting",
                                self.peer,
                                bm.piece,
                            )
                            md_msg = BEP9Message(
                                msg_type=BEP9MsgType.REJECT, piece=bm.piece
                            )
                            await self.send(md_msg.compose(UT_METADATA))
                        else:
                            ### TODO: Do nothing?  Debug-log?
                            self.error(
                                "received ut_metadata message with"
                                f" unexpected msg_type {bm.msg_type.name!r}"
                            )
        log.debug("All info pieces received from %s; validating ...", self.peer)
        if (good_dgst := self.info_hash.as_hex) != (dgst := info_piecer.get_digest()):
            self.error(
                f"Received info with invalid digest; expected {good_dgst}, got {dgst}"
            )
        data = info_piecer.get_data()
        try:
            info = unbencode(data)
            assert isinstance(info, dict)
        except (UnbencodeError, AssertionError):
            self.error("Received invalid bencoded data as info")
        return info
