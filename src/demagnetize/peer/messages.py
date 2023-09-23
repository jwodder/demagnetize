# NOTE: Avoid using slotted classes here, as combining them with attrs and
# `__subclasses__` can lead to Heisenbugs depending on when garbage collection
# happens.
from __future__ import annotations
from abc import ABC, abstractmethod
from collections import deque
from functools import reduce
from operator import or_
import struct
from typing import Any, ClassVar, Optional
import attr
from .extensions import BEP9MsgType, BEP10Extension, BEP10Registry, Extension
from ..bencode import bencode, partial_unbencode, unbencode
from ..errors import UnbencodeError
from ..util import InfoHash, get_string, get_typed_value


@attr.define(slots=False)
class Handshake:
    HEADER: ClassVar[bytes] = b"\x13BitTorrent protocol"
    LENGTH: ClassVar[int] = 20 + 8 + 20 + 20

    extensions: set[int]
    info_hash: InfoHash
    peer_id: bytes

    def __str__(self) -> str:
        extensions = ", ".join(self.extension_names) or "<none>"
        return f"handshake; extensions: {extensions}; peer_id: {self.peer_id!r}"

    def __bytes__(self) -> bytes:
        return (
            self.HEADER
            + reduce(or_, [1 << i for i in self.extensions], 0).to_bytes(8, "big")
            + bytes(self.info_hash)
            + (self.peer_id + b"\0" * 20)[:20]
        )

    @classmethod
    def parse(cls, blob: bytes) -> Handshake:
        if len(blob) != cls.LENGTH:
            raise ValueError(
                f"handshake wrong length; got {len(blob)} bytes, expected {cls.LENGTH}"
            )
        if blob[: len(cls.HEADER)] != cls.HEADER:
            raise ValueError("handshake had invalid protocol declaration")
        offset = len(cls.HEADER)
        exts = int.from_bytes(blob[offset : offset + 8], "big")
        extensions = {i for i in range(64) if exts & (1 << i)}
        offset += 8
        info_hash = InfoHash.from_bytes(blob[offset : offset + 20])
        offset += 20
        peer_id = blob[offset:]
        return cls(extensions=extensions, info_hash=info_hash, peer_id=peer_id)

    @property
    def extension_names(self) -> list[str]:
        extnames: list[str] = []
        for ext in sorted(self.extensions):
            try:
                extnames.append(Extension(ext).name)
            except ValueError:
                extnames.append(str(ext))
        return extnames


@attr.define(slots=False)
class Message(ABC):
    TYPE: ClassVar[int]

    def __bytes__(self) -> bytes:
        payload = self.to_payload()
        length = 1 + len(payload)
        return length.to_bytes(4, "big") + bytes([self.TYPE]) + payload

    @classmethod
    def parse(cls, blob: bytes) -> Message:
        # length = blob[:4]
        mtype = blob[4]
        payload = blob[5:]
        klasses = deque(Message.__subclasses__())
        while klasses:
            klass = klasses.popleft()
            if hasattr(klass, "TYPE"):
                if klass.TYPE == mtype:
                    return klass.from_payload(payload)
            else:
                klasses.extend(klass.__subclasses__())
        raise ValueError(f"Unknown message type: {mtype}")

    @classmethod
    @abstractmethod
    def from_payload(cls, payload: bytes) -> Message:
        ...

    @abstractmethod
    def to_payload(self) -> bytes:
        ...


@attr.define(slots=False)  # To make the empty messages into useful classes
class EmptyMessage(Message):
    @classmethod
    def from_payload(cls, _payload: bytes) -> EmptyMessage:
        ### TODO: Do something if payload is not empty?
        return cls()

    def to_payload(self) -> bytes:
        return b""


class Choke(EmptyMessage):
    TYPE = 0

    def __str__(self) -> str:
        return "choke"


class Unchoke(EmptyMessage):
    TYPE = 1

    def __str__(self) -> str:
        return "unchoke"


class Interested(EmptyMessage):
    TYPE = 2

    def __str__(self) -> str:
        return "interested"


class NotInterested(EmptyMessage):
    TYPE = 3

    def __str__(self) -> str:
        return "not interested"


class HaveAll(EmptyMessage):
    TYPE = 0x0E

    def __str__(self) -> str:
        return "have all"


class HaveNone(EmptyMessage):
    TYPE = 0x0F

    def __str__(self) -> str:
        return "have none"


@attr.define(slots=False)
class Have(Message):
    TYPE: ClassVar[int] = 4
    index: int

    def __str__(self) -> str:
        return f"have piece {self.index}"

    @classmethod
    def from_payload(cls, payload: bytes) -> Have:
        if len(payload) != 4:
            raise ValueError(
                f"Invalid length for 'have' payload; expected 4 bytes,"
                f" got {len(payload)}"
            )
        return cls(index=int.from_bytes(payload, "big"))

    def to_payload(self) -> bytes:
        return self.index.to_bytes(4, "big")


@attr.define(slots=False)
class Bitfield(Message):
    TYPE: ClassVar[int] = 5
    payload: bytes

    def __str__(self) -> str:
        return f"have {self.have_amount} pieces"

    @classmethod
    def from_payload(cls, payload: bytes) -> Bitfield:
        return cls(payload)

    def to_payload(self) -> bytes:
        return self.payload

    @property
    def have_amount(self) -> int:
        qty = 0
        for b in self.payload:
            for i in range(8):
                if b & (1 << i):
                    qty += 1
        return qty


@attr.define(slots=False)
class Request(Message):
    TYPE: ClassVar[int] = 6
    index: int
    begin: int
    length: int

    def __str__(self) -> str:
        return f"request piece {self.index}, offset {self.begin}, length {self.length}"

    @classmethod
    def from_payload(cls, payload: bytes) -> Request:
        if len(payload) != 12:
            raise ValueError(
                f"Invalid length for 'request' payload; expected 12 bytes,"
                f" got {len(payload)}"
            )
        index, begin, length = struct.unpack("!III", payload)
        return cls(index, begin, length)

    def to_payload(self) -> bytes:
        return struct.pack("!III", self.index, self.begin, self.length)


@attr.define(slots=False)
class Piece(Message):
    TYPE: ClassVar[int] = 7
    index: int
    begin: int
    data: bytes

    def __str__(self) -> str:
        return f"piece {self.index}, offset {self.begin}, length {len(self.data)}"

    @classmethod
    def from_payload(cls, payload: bytes) -> Piece:
        if len(payload) < 8:
            raise ValueError(
                f"Invalid length for 'piece' payload; expected 8+ bytes,"
                f" got {len(payload)}"
            )
        index, begin = struct.unpack_from("!II", payload)
        return cls(index, begin, payload[8:])

    def to_payload(self) -> bytes:
        return struct.pack("!II", self.index, self.begin) + self.data


@attr.define(slots=False)
class Cancel(Message):
    TYPE: ClassVar[int] = 8
    index: int
    begin: int
    length: int

    def __str__(self) -> str:
        return (
            f"cancel request for piece {self.index}, offset {self.begin},"
            f" length {self.length}"
        )

    @classmethod
    def from_payload(cls, payload: bytes) -> Cancel:
        if len(payload) != 12:
            raise ValueError(
                f"Invalid length for 'cancel' payload; expected 12 bytes,"
                f" got {len(payload)}"
            )
        index, begin, length = struct.unpack("!III", payload)
        return cls(index, begin, length)

    def to_payload(self) -> bytes:
        return struct.pack("!III", self.index, self.begin, self.length)


@attr.define(slots=False)
class Port(Message):
    TYPE: ClassVar[int] = 9
    port: int

    def __str__(self) -> str:
        return f"DHT port {self.port}"

    @classmethod
    def from_payload(cls, payload: bytes) -> Port:
        if len(payload) != 2:
            raise ValueError(
                f"Invalid length for 'port' payload; expected 2 bytes,"
                f" got {len(payload)}"
            )
        return cls(int.from_bytes(payload, "big"))

    def to_payload(self) -> bytes:
        return self.port.to_bytes(2, "big")


@attr.define(slots=False)
class Reject(Message):
    TYPE: ClassVar[int] = 0x10
    index: int
    begin: int
    length: int

    def __str__(self) -> str:
        return (
            f"reject request for piece {self.index}, offset {self.begin},"
            f" length {self.length}"
        )

    @classmethod
    def from_payload(cls, payload: bytes) -> Reject:
        if len(payload) != 12:
            raise ValueError(
                f"Invalid length for 'reject' payload; expected 12 bytes,"
                f" got {len(payload)}"
            )
        index, begin, length = struct.unpack("!III", payload)
        return cls(index, begin, length)

    def to_payload(self) -> bytes:
        return struct.pack("!III", self.index, self.begin, self.length)


@attr.define(slots=False)
class AllowedFast(Message):
    TYPE: ClassVar[int] = 0x11
    index: int

    def __str__(self) -> str:
        return f"allow fast download of piece {self.index}"

    @classmethod
    def from_payload(cls, payload: bytes) -> AllowedFast:
        if len(payload) != 4:
            raise ValueError(
                f"Invalid length for 'allowed fast' payload; expected 4 bytes,"
                f" got {len(payload)}"
            )
        index = int.from_bytes(payload, "big")
        return cls(index=index)

    def to_payload(self) -> bytes:
        return self.index.to_bytes(4, "big")


@attr.define(slots=False)
class Suggest(Message):
    TYPE: ClassVar[int] = 0x0D
    index: int

    def __str__(self) -> str:
        return f"suggest piece {self.index}"

    @classmethod
    def from_payload(cls, payload: bytes) -> Suggest:
        if len(payload) != 4:
            raise ValueError(
                f"Invalid length for 'suggest' payload; expected 4 bytes,"
                f" got {len(payload)}"
            )
        index = int.from_bytes(payload, "big")
        return cls(index=index)

    def to_payload(self) -> bytes:
        return self.index.to_bytes(4, "big")


@attr.define(slots=False)
class Extended(Message):
    TYPE: ClassVar[int] = 20
    msg_id: int
    payload: bytes

    def __str__(self) -> str:
        return f"extended message, ID {self.msg_id}"

    @classmethod
    def from_payload(cls, payload: bytes) -> Extended:
        if len(payload) < 1:
            raise ValueError(
                f"Invalid length for 'extended' payload; expected 1+ bytes,"
                f" got {len(payload)}"
            )
        return cls(payload[0], payload[1:])

    def to_payload(self) -> bytes:
        return bytes([self.msg_id]) + self.payload

    def decompose(
        self, extensions: BEP10Registry
    ) -> ExtendedHandshake | ExtendedMessage:
        if self.msg_id == 0:
            return ExtendedHandshake.from_extended_payload(self.payload)
        else:
            try:
                ext = extensions.from_code[self.msg_id]
            except KeyError:
                raise ValueError(f"Unknown extended message ID {self.msg_id}")
            for klass in ExtendedMessage.__subclasses__():
                if klass.EXTENSION == ext:
                    return klass.from_extended_payload(self.payload)
            raise ValueError(f"Unimplemented extended message ID {self.msg_id}")


@attr.define(slots=False)
class ExtendedHandshake:
    data: dict

    def __str__(self) -> str:
        s = "BEP 10 extended handshake; extensions: " + (
            ", ".join(self.extension_names) or "<none>"
        )
        if self.client is not None:
            s += f"; client: {self.client}"
        return s

    @classmethod
    def make(
        cls,
        extensions: BEP10Registry,
        client: Optional[str] = None,
        metadata_size: Optional[int] = None,
    ) -> ExtendedHandshake:
        data: dict[bytes, Any] = {b"m": extensions.to_m()}
        if client is not None:
            data[b"v"] = client.encode("utf-8")
        if metadata_size is not None:
            data[b"metadata_size"] = metadata_size
        return cls(data)

    @classmethod
    def from_extended_payload(cls, payload: bytes) -> ExtendedHandshake:
        try:
            data = unbencode(payload)
        except UnbencodeError as e:
            raise ValueError(f"invalid bencoded data: {e}")
        if not isinstance(data, dict):
            raise ValueError("payload is not a dict")
        if not isinstance(data.get(b"m"), dict):
            raise ValueError("'m' dictionary missing")
        return cls(data)

    def to_extended_payload(self) -> bytes:
        return bencode(self.data)

    def to_extended(self) -> Extended:
        return Extended(msg_id=0, payload=self.to_extended_payload())

    @property
    def extension_names(self) -> list[str]:
        exts: list[str] = []
        for k in self.data[b"m"]:
            assert isinstance(k, bytes)
            exts.append(k.decode("utf-8", "replace"))
        return exts

    @property
    def extensions(self) -> BEP10Registry:
        return BEP10Registry.from_m(self.data[b"m"])

    @property
    def client(self) -> Optional[str]:
        return get_string(self.data, b"v")

    @property
    def metadata_size(self) -> Optional[int]:
        return get_typed_value(self.data, b"metadata_size", int)


@attr.define(slots=False)
class ExtendedMessage(ABC):
    EXTENSION: ClassVar[BEP10Extension]

    @classmethod
    @abstractmethod
    def from_extended_payload(cls, payload: bytes) -> ExtendedMessage:
        ...

    @abstractmethod
    def to_extended_payload(self) -> bytes:
        ...

    def to_extended(self, extensions: BEP10Registry) -> Extended:
        msg_id = extensions.to_code[self.EXTENSION]
        return Extended(msg_id=msg_id, payload=self.to_extended_payload())


@attr.define(slots=False)
class BEP9Message(ExtendedMessage):
    EXTENSION: ClassVar[BEP10Extension] = BEP10Extension.METADATA

    msg_type: int
    piece: int
    total_size: Optional[int] = None
    payload: bytes = b""

    def __str__(self) -> str:
        try:
            typename = BEP9MsgType(self.msg_type).name
        except ValueError:
            typename = f"msg_type {self.msg_type}"
        return f"ut_metadata message ({typename} piece {self.piece})"

    @classmethod
    def from_extended_payload(cls, payload: bytes) -> BEP9Message:
        try:
            data, trailing = partial_unbencode(payload)
        except UnbencodeError as e:
            raise ValueError(
                f"ut_metadata message does not start with valid bencode: {e}"
            )
        if not isinstance(data, dict):
            raise ValueError("ut_metadata message does not start with a dict")
        if not isinstance(msg_type := data.get(b"msg_type"), int):
            raise ValueError("ut_metadata message lacks valid 'msg_type' field")
        if not isinstance(piece := data.get(b"piece"), int):
            raise ValueError("ut_metadata message lacks valid 'piece' field")
        total_size = data.get(b"total_size")
        if total_size is not None and not isinstance(total_size, int):
            raise ValueError("ut_metadata message has invalid 'total_size' field")
        try:
            mt = BEP9MsgType(msg_type)
        except ValueError:
            pass
        else:
            if mt is not BEP9MsgType.DATA:
                if trailing:
                    raise ValueError("Non-data ut_metadata message has trailing bytes")
            elif not trailing:
                raise ValueError("ut_metadata data message lacks trailing data")
        return cls(
            msg_type=msg_type,
            piece=piece,
            total_size=total_size,
            payload=trailing,
        )

    def to_extended_payload(self) -> bytes:
        data = {b"msg_type": self.msg_type, b"piece": self.piece}
        if self.total_size is not None:
            data[b"total_size"] = self.total_size
        return bencode(data) + self.payload


AnyMessage = Message | ExtendedHandshake | ExtendedMessage


def decode_message(blob: bytes, extensions: BEP10Registry) -> AnyMessage:
    msg = Message.parse(blob)
    if isinstance(msg, Extended):
        return msg.decompose(extensions)
    else:
        return msg


def encode_message(msg: AnyMessage, extensions: BEP10Registry) -> bytes:
    if isinstance(msg, ExtendedHandshake):
        msg = msg.to_extended()
    elif isinstance(msg, ExtendedMessage):
        msg = msg.to_extended(extensions)
    return bytes(msg)
