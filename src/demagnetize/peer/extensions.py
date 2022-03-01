from __future__ import annotations
from enum import Enum
from typing import Dict, Iterable, Set
import attr


class Extension(Enum):
    AZUREUS_MESSAGING = (0, 0x80)
    LOCATION_AWARE = (2, 0x08)
    BEP10_EXTENSIONS = (5, 0x10)
    DHT = (7, 0x01)
    XBT_PEX = (7, 0x02)
    FAST = (7, 0x04)
    NAT_TRAVERSAL = (7, 0x08)
    HYBRID_V2 = (7, 0x10)

    def __init__(self, byte: int, mask: int) -> None:
        self.byte = byte
        self.mask = mask

    @staticmethod
    def compile(extensions: Iterable[Extension]) -> bytes:
        bs = [0] * 8
        for ext in extensions:
            bs[ext.byte] |= ext.mask
        return bytes(bs)

    @classmethod
    def decompile(cls, blob: bytes) -> Set[Extension]:
        return {ext for ext in cls if ext.is_set(blob)}

    def is_set(self, blob: bytes) -> bool:
        return blob[self.byte] & self.mask == self.mask


class BEP10Extension(Enum):
    METADATA = "ut_metadata"
    PEX = "ut_pex"


@attr.define
class BEP10Registry:
    from_code: Dict[int, BEP10Extension] = attr.Factory(dict)
    to_code: Dict[BEP10Extension, int] = attr.Factory(dict)

    def __contains__(self, ext: BEP10Extension) -> bool:
        return ext in self.to_code

    @classmethod
    def from_handshake_m(cls, m: dict) -> BEP10Registry:
        msg_ids = cls()
        for k, v in m.items():
            if not isinstance(k, bytes):
                continue
            try:
                bext = BEP10Extension(k.decode("utf-8", "replace"))
            except ValueError:
                continue
            if isinstance(v, int):
                msg_ids.register(bext, v)
        return msg_ids

    @property
    def extensions(self) -> Set[BEP10Extension]:
        return set(self.to_code.keys())

    def register(self, ext: BEP10Extension, code: int) -> None:
        if code in self.from_code:
            raise ValueError(f"conflicting declarations for code {code}")
        if ext in self.to_code:
            raise ValueError(f"conflicting declarations for key {ext.value!r}")
        self.from_code[code] = ext
        self.to_code[ext] = code

    def as_dict(self) -> Dict[bytes, int]:
        return {k.value.encode("utf-8"): v for k, v in self.to_code.items()}


class BEP9MsgType(Enum):
    REQUEST = 0
    DATA = 1
    REJECT = 2
