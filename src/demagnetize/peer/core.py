from __future__ import annotations
from contextlib import asynccontextmanager
import sys
from typing import TYPE_CHECKING, Any, AsyncIterator, Dict, List, Optional, Set, Tuple
from anyio import (
    EndOfStream,
    IncompleteRead,
    connect_tcp,
    create_memory_object_stream,
    create_task_group,
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
from ..consts import CLIENT, KEEPALIVE_PERIOD, MAX_PEER_MSG_LEN, UT_METADATA
from ..errors import CellClosedError, PeerError, UnknownBEP9MsgType
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

PeerAddress = Tuple[str, int]


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

    def for_json(self) -> Dict[str, Any]:
        pid: Optional[str]
        if self.id is not None:
            pid = self.id.decode("utf-8", "replace")
        else:
            pid = None
        return {"host": self.host, "port": self.port, "id": pid}

    async def get_info(
        self, app: Demagnetizer, info_hash: InfoHash, info_piecer: InfoPiecer
    ) -> None:
        # Returns number of pieces received
        log.info("Requesting info for %s from %s", info_hash, self)
        try:
            async with self.connect(app, info_hash) as connpeer:
                await connpeer.get_info(info_piecer)
        except OSError as e:
            raise PeerError(f"Error communicating with {self}: {type(e).__name__}: {e}")

    @asynccontextmanager
    async def connect(
        self, app: Demagnetizer, info_hash: InfoHash
    ) -> AsyncIterator[PeerConnection]:
        log.debug("Connecting to %s", self)
        async with await connect_tcp(self.host, self.port) as s:
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
    extensions: Set[Extension] = attr.Factory(set)
    bep10_handshake: AsyncCell[ExtendedHandshake] = attr.Factory(AsyncCell)
    subscribers: List[Subscriber] = attr.Factory(list)
    readstream: BufferedByteReceiveStream = attr.field(init=False)

    def __attrs_post_init__(self) -> None:
        self.readstream = BufferedByteReceiveStream(self.socket)

    async def aclose(self) -> None:
        for s in self.subscribers:
            await s.aclose()
        self.task_group.cancel_scope.cancel()
        await self.readstream.aclose()
        await self.socket.aclose()

    async def send(self, msg: Message) -> None:
        log.log(TRACE, "Sending to %s: %s", self.peer, msg)
        await self.socket.send(bytes(msg))

    async def read(self, length: int) -> bytes:
        try:
            return await self.readstream.receive_exactly(length)
        except (EndOfStream, IncompleteRead):
            raise PeerError(f"{self.peer} closed the connection early")

    async def handshake(self) -> None:
        log.log(TRACE, "Sending handshake to %s", self.peer)
        await self.socket.send(
            bytes(
                Handshake(
                    extensions=SUPPORTED_EXTENSIONS,
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
            raise PeerError(f"{self.peer} sent bad handshake: {e}")
        log.debug(
            "%s sent handshake: extensions=%s, peer_id=%s",
            self.peer,
            " | ".join(ext.name for ext in hs.extensions) or "<none>",
            hs.peer_id.decode("utf-8", "replace"),
        )
        if hs.info_hash != self.info_hash:
            raise PeerError(
                f"{self.peer} replied with wrong info hash;"
                f" got {hs.info_hash}, asked for {self.info_hash}"
            )
        self.extensions = SUPPORTED_EXTENSIONS & hs.extensions
        if Extension.BEP10_EXTENSIONS in self.extensions:
            self.subscribers.append(ExtendedHandshakeSubscriber(self))
            handshake = ExtendedHandshake(extensions=BEP10_EXTENSIONS, v=CLIENT)
            await self.send(handshake.compose())
        else:
            raise PeerError(f"{self.peer} does not support BEP 10 extensions")
        if Extension.FAST in self.extensions:
            await self.send(HaveNone())

    def start_tasks(self) -> None:
        self.subscribers.append(MessageSink())
        self.task_group.start_soon(self.handle_messages)
        self.task_group.start_soon(self.send_keepalives)

    async def aiter_messages(self) -> AsyncIterator[Message]:
        while True:
            blob = await self.read(4)
            length = int.from_bytes(blob, "big")
            if length > MAX_PEER_MSG_LEN:
                raise PeerError(
                    f"{self.peer} tried to send overly large message of"
                    f" {length} bytes; not trusting"
                )
            if length == 0:
                log.log(TRACE, "%s sent keepalive", self.peer)
            else:
                blob = await self.read(length)
            try:
                msg = Message.parse(blob)
            except ValueError as e:
                log.log(TRACE, "Bad message from %s: %r", self.peer, blob)
                raise PeerError(f"{self.peer} sent invalid message: {e}")
            yield msg

    async def handle_messages(self) -> None:
        async with aclosing(self.aiter_messages()) as ait:
            async for msg in ait:
                log.debug("%s sent message: %s", self.peer, msg)
                notified = False
                for s in list(self.subscribers):
                    if s.match(msg):
                        await s.notify(msg)
                        notified = True
                if not notified:
                    raise PeerError(f"{self.peer} sent unexpected message: {msg}")

    async def send_keepalives(self) -> None:
        while True:
            await sleep(KEEPALIVE_PERIOD)
            log.log(TRACE, "Sending keepalive to %s", self.peer)
            await self.socket.send(b"\0\0\0\0")

    async def get_info(self, info_piecer: InfoPiecer) -> None:
        try:
            ### TODO: Put a timeout on this:
            handshake = await self.bep10_handshake.get()
        except CellClosedError:
            raise PeerError("Abandoned connection")
        if BEP10Extension.METADATA not in handshake.extensions:
            raise PeerError(f"{self.peer} does not support metadata transfer")
        if handshake.metadata_size is None:
            raise PeerError(
                f"{self.peer} did not report info size in extended handshake"
            )
        log.debug(
            "%s declares info size as %d bytes", self.peer, handshake.metadata_size
        )
        try:
            info_piecer.set_size(handshake.metadata_size)
        except ValueError as e:
            raise PeerError(
                f"Info size reported by {self.peer} conflicts with previous"
                f" information: {e}"
            )
        sender, receiver = create_memory_object_stream(0, Extended)
        async with sender, receiver:
            channeller = ExtendedMessageChanneller(UT_METADATA, sender)
            with additem(self.subscribers, channeller):
                for i in info_piecer.needed():
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
                            log.debug(
                                "%s sent ut_metadata message with unknown"
                                " msg_type %d; ignoring",
                                self.peer,
                                e.msg_type,
                            )
                            continue
                        except ValueError as e:
                            raise PeerError(
                                f"received invalid ut_metadata message: {e}"
                            )
                        if bm.msg_type is BEP9MsgType.DATA:
                            if bm.piece != i:
                                raise PeerError(
                                    "received data for info piece"
                                    f" {bm.piece}, which we did not request"
                                )
                            elif (
                                bm.total_size is not None
                                and bm.total_size != info_piecer.size
                            ):
                                raise PeerError(
                                    "'total_size' in info data message"
                                    f" ({bm.total_size}) differs from"
                                    f" previous value ({info_piecer.size})"
                                )
                            log.debug("%s sent info piece %d", self.peer, bm.piece)
                            try:
                                info_piecer.set_piece(self.peer, bm.piece, bm.payload)
                            except ValueError as e:
                                raise PeerError(f"bad info piece: {e}")
                            break
                        elif bm.msg_type is BEP9MsgType.REJECT:
                            if bm.piece != i:
                                raise PeerError(
                                    "received reject for info piece"
                                    f" {bm.piece}, which we did not request"
                                )
                            log.debug(
                                "%s rejected request for info piece %d",
                                self.peer,
                                bm.piece,
                            )
                        elif bm.msg_type is BEP9MsgType.REQUEST:
                            log.debug(
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
                            raise PeerError(
                                "received ut_metadata message with"
                                f" unexpected msg_type {bm.msg_type.name!r}"
                            )
