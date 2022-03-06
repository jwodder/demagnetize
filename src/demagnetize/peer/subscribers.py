from __future__ import annotations
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING
from anyio.streams.memory import MemoryObjectSendStream
import attr
from .messages import (
    AllowedFast,
    BEP9Message,
    Bitfield,
    EmptyMessage,
    ExtendedHandshake,
    Have,
    MessageType,
    Piece,
    Suggest,
)
from ..util import log

if TYPE_CHECKING:
    from .core import PeerConnection


class Subscriber(ABC):
    @abstractmethod
    async def notify(self, msg: MessageType) -> bool:
        ...

    @abstractmethod
    async def aclose(self) -> None:
        ...


class MessageSink(Subscriber):
    async def notify(self, msg: MessageType) -> bool:
        return isinstance(
            msg, (EmptyMessage, Have, Bitfield, Piece, AllowedFast, Suggest)
        )

    async def aclose(self) -> None:
        pass


@attr.define
class ExtendedHandshakeSubscriber(Subscriber):
    conn: PeerConnection

    async def notify(self, msg: MessageType) -> bool:
        if isinstance(msg, ExtendedHandshake):
            self.conn.subscribers.remove(self)
            if msg.client is not None:
                extra = f"; client: {msg.client}"
            else:
                extra = ""
            log.debug(
                "%s sent BEP 10 extended handshake; extensions: %s%s",
                self.conn.peer,
                ", ".join(msg.extension_names) or "<none>",
                extra,
            )
            self.conn.bep10_handshake.set(msg)
            return True
        else:
            return False

    async def aclose(self) -> None:
        self.conn.bep10_handshake.close()


@attr.define
class BEP9MessageChanneller(Subscriber):
    sender: MemoryObjectSendStream[BEP9Message]

    async def notify(self, msg: MessageType) -> bool:
        if isinstance(msg, BEP9Message):
            await self.sender.send(msg)
            return True
        else:
            return False

    async def aclose(self) -> None:
        await self.sender.aclose()
