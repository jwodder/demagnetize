from __future__ import annotations
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING
from anyio.streams.memory import MemoryObjectSendStream
import attr
from .messages import (
    AllowedFast,
    Bitfield,
    EmptyMessage,
    Extended,
    ExtendedHandshake,
    Have,
    Message,
    Piece,
    Suggest,
)
from ..util import log

if TYPE_CHECKING:
    from .core import PeerConnection


class Subscriber(ABC):
    @abstractmethod
    def match(self, msg: Message) -> bool:
        ...

    @abstractmethod
    async def notify(self, msg: Message) -> None:
        ...

    @abstractmethod
    async def aclose(self) -> None:
        ...


class MessageSink(Subscriber):
    def match(self, msg: Message) -> bool:
        return isinstance(
            msg, (EmptyMessage, Have, Bitfield, Piece, AllowedFast, Suggest)
        )

    async def notify(self, _msg: Message) -> None:
        pass

    async def aclose(self) -> None:
        pass


@attr.define
class ExtendedHandshakeSubscriber(Subscriber):
    conn: PeerConnection

    def match(self, msg: Message) -> bool:
        return isinstance(msg, Extended) and msg.msg_id == 0

    async def notify(self, msg: Message) -> None:
        self.conn.subscribers.remove(self)
        assert isinstance(msg, Extended)
        try:
            handshake = ExtendedHandshake.parse(msg.payload)
        except ValueError as e:
            self.conn.error(f"Peer sent invalid extension handshake: {e}")
        if handshake.client is not None:
            extra = f"; client: {handshake.client}"
        else:
            extra = ""
        log.debug(
            "%s sent BEP 10 extended handshake; extensions: %s%s",
            self.conn.peer,
            ", ".join(handshake.extension_names) or "<none>",
            extra,
        )
        self.conn.bep10_handshake.set(handshake)

    async def aclose(self) -> None:
        self.conn.bep10_handshake.close()


@attr.define
class ExtendedMessageChanneller(Subscriber):
    msg_id: int
    sender: MemoryObjectSendStream[Extended]

    def match(self, msg: Message) -> bool:
        return isinstance(msg, Extended) and msg.msg_id == self.msg_id

    async def notify(self, msg: Message) -> None:
        assert isinstance(msg, Extended)
        await self.sender.send(msg)

    async def aclose(self) -> None:
        await self.sender.aclose()
