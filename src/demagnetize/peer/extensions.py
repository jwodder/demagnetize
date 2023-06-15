from __future__ import annotations
from enum import Enum, IntEnum
import attr


def extbit(bytenum: int, mask: int) -> int:
    for i in range(8):
        if 1 << i == mask:
            return i + 8 * (7 - bytenum)
    raise ValueError("Mask must be a single bit")


class Extension(IntEnum):
    AZUREUS_MESSAGING = extbit(0, 0x80)
    LOCATION_AWARE = extbit(2, 0x08)
    BEP10_EXTENSIONS = extbit(5, 0x10)
    DHT = extbit(7, 0x01)
    XBT_PEX = extbit(7, 0x02)
    FAST = extbit(7, 0x04)
    NAT_TRAVERSAL = extbit(7, 0x08)
    HYBRID_V2 = extbit(7, 0x10)


class BEP10Extension(Enum):
    METADATA = "ut_metadata"
    PEX = "ut_pex"


@attr.define
class BEP10Registry:
    from_code: dict[int, BEP10Extension] = attr.Factory(dict)
    to_code: dict[BEP10Extension, int] = attr.Factory(dict)

    def __contains__(self, ext: BEP10Extension) -> bool:
        return ext in self.to_code

    @classmethod
    def from_dict(cls, d: dict[BEP10Extension, int]) -> BEP10Registry:
        msg_ids = cls()
        for ext, code in d.items():
            msg_ids.register(ext, code)
        return msg_ids

    @classmethod
    def from_m(cls, m: dict) -> BEP10Registry:
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

    def register(self, ext: BEP10Extension, code: int) -> None:
        if code in self.from_code:
            raise ValueError(f"conflicting declarations for code {code}")
        if ext in self.to_code:
            raise ValueError(f"conflicting declarations for key {ext.value!r}")
        self.from_code[code] = ext
        self.to_code[ext] = code

    def to_m(self) -> dict[bytes, int]:
        return {k.value.encode("utf-8"): v for k, v in self.to_code.items()}


class BEP9MsgType(IntEnum):
    REQUEST = 0
    DATA = 1
    REJECT = 2
