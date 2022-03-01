from __future__ import annotations
from abc import ABC, abstractmethod
from collections import deque
import struct
from typing import Any, ClassVar, Dict, Optional, Set
import attr
from .extensions import BEP9MsgType, BEP10Registry, Extension
from ..bencode import bencode, partial_unbencode, unbencode
from ..errors import UnbencodeError, UnknownBEP9MsgType
from ..util import InfoHash


@attr.define
class Handshake:
    HEADER: ClassVar[bytes] = b"\x13BitTorrent protocol"
    LENGTH: ClassVar[int] = 20 + 8 + 20 + 20

    extensions: Set[Extension]
    info_hash: InfoHash
    peer_id: bytes

    @classmethod
    def parse(cls, blob: bytes) -> Handshake:
        if len(blob) != cls.LENGTH:
            raise ValueError(
                f"handshake wrong length; got {len(blob)}, expected {cls.LENGTH}"
            )
        if blob[: len(cls.HEADER)] != cls.HEADER:
            raise ValueError("handshake had invalid protocol declaration")
        offset = len(cls.HEADER)
        extensions = Extension.decompile(blob[offset : offset + 8])
        offset += 8
        info_hash = InfoHash.from_bytes(blob[offset : offset + 20])
        offset += 20
        peer_id = blob[offset:]
        return cls(extensions=extensions, info_hash=info_hash, peer_id=peer_id)

    def __bytes__(self) -> bytes:
        return (
            self.HEADER
            + Extension.compile(self.extensions)
            + bytes(self.info_hash)
            + (self.peer_id + b"\0" * 20)[:20]
        )


class Message(ABC):
    TYPE: ClassVar[int]

    def __bytes__(self) -> bytes:
        payload = self.to_payload()
        length = 1 + len(payload)
        return length.to_bytes(4, "big") + bytes([self.TYPE]) + payload

    @classmethod
    def parse(cls, blob: bytes) -> Message:
        mtype = blob[0]
        payload = blob[1:]
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


@attr.define
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
        index = int.from_bytes(payload, "big")
        return cls(index=index)

    def to_payload(self) -> bytes:
        return self.index.to_bytes(4, "big")


@attr.define
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


@attr.define
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


@attr.define
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


@attr.define
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


@attr.define
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


@attr.define
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


@attr.define
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


@attr.define
class Extended(Message):
    TYPE: ClassVar[int] = 20
    msg_id: int
    payload: bytes

    def __str__(self) -> str:
        return f"extended message, ID {self.msg_id}"

    @classmethod
    def from_payload(cls, payload: bytes) -> Extended:
        if len(payload) < 8:
            raise ValueError(
                f"Invalid length for 'extended' payload; expected 1+ bytes,"
                f" got {len(payload)}"
            )
        return cls(payload[0], payload[1:])

    def to_payload(self) -> bytes:
        return bytes([self.msg_id]) + self.payload


@attr.define
class ExtendedHandshake:
    extensions: BEP10Registry
    v: Optional[str] = None
    metadata_size: Optional[int] = None

    @classmethod
    def parse(cls, payload: bytes) -> ExtendedHandshake:
        try:
            data = unbencode(payload)
        except UnbencodeError:
            raise ValueError("invalid bencoded data")
        m = data.get(b"m")
        if not isinstance(m, dict):
            raise ValueError("'m' dictionary missing")
        handshake = cls(extensions=BEP10Registry.from_handshake_m(m))
        if isinstance(v := data.get(b"v"), bytes):
            handshake.v = v.decode("utf-8", "replace")
        if isinstance(size := data.get(b"metadata_size"), int):
            handshake.metadata_size = size
        return handshake

    def compose(self) -> Extended:
        data: Dict[bytes, Any] = {b"m": self.extensions.as_dict()}
        if self.v is not None:
            data[b"v"] = self.v.encode("utf-8")
        if self.metadata_size is not None:
            data[b"metadata-size"] = self.metadata_size
        return Extended(msg_id=0, payload=bencode(data))


@attr.define
class BEP9Message:
    msg_type: BEP9MsgType
    piece: int
    total_size: Optional[int] = None
    payload: bytes = b""

    @classmethod
    def parse(cls, payload: bytes) -> BEP9Message:
        try:
            data, trailing = partial_unbencode(payload)
        except UnbencodeError:
            raise ValueError("ut_metadata message does not start with valid bencode")
        if not isinstance(data, dict):
            raise ValueError("ut_metadata message does not start with a dict")
        if not isinstance(mt := data.get(b"msg_type"), int):
            raise ValueError("ut_metadata message lacks valid 'msg_type' field")
        try:
            msg_type = BEP9MsgType(mt)
        except ValueError:
            raise UnknownBEP9MsgType(mt)
        if not isinstance(piece := data.get(b"piece"), int):
            raise ValueError("ut_metadata message lacks valid 'piece' field")
        total_size = data.get(b"total_size")
        if total_size is not None and not isinstance(total_size, int):
            raise ValueError("ut_metadata message has invalid 'total_size' field")
        if msg_type != BEP9MsgType.DATA:
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

    def compose(self, msg_id: int) -> Extended:
        data = {b"msg_type": self.msg_type.value, b"piece": self.piece}
        if self.total_size is not None:
            data[b"total_size"] = self.total_size
        benc = bencode(data)
        return Extended(msg_id=msg_id, payload=benc + self.payload)
