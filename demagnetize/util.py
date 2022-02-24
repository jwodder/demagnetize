from __future__ import annotations
from dataclasses import dataclass
from binascii import unhexlify
from base64 import b32decode


@dataclass
class InfoHash:
    as_str: str
    as_bytes: bytes

    @classmethod
    def from_string(cls, s: str) -> InfoHash:
        if len(s) == 40:
            b = unhexlify(s)
        elif len(s) == 32:
            b = b32decode(s)
        else:
            raise ValueError(f"Invalid info hash: {s!r}")
        return cls(as_str=s, as_bytes=b)

    def __str__(self) -> str:
        return self.as_str

    def __bytes__(self) -> bytes:
        return self.as_bytes
