from __future__ import annotations
from typing import Any, Optional
import attr
from .errors import UnbencodeError


def bencode(obj: Any) -> bytes:
    if isinstance(obj, bytes):
        return b"%d:%b" % (len(obj), obj)
    elif isinstance(obj, int):
        return b"i%de" % (obj,)
    elif isinstance(obj, list):
        return b"l" + b"".join(bencode(o) for o in obj) + b"e"
    elif isinstance(obj, dict):
        s = b"d"
        for key in sorted(obj.keys()):
            if not isinstance(key, bytes):
                raise TypeError(f"Cannot bencode {type(key).__name__} dict keys")
            s += bencode(key) + bencode(obj[key])
        return s + b"e"
    else:
        raise TypeError(f"Cannot bencode {type(obj).__name__}")


@attr.define
class Unbencoder:
    buff: bytes
    index: int = 0

    def getchar(self) -> bytes:
        if self.index < len(self.buff):
            b = self.buff[self.index : self.index + 1]
            self.index += 1
            return b
        else:
            raise UnbencodeError("Short input")

    def peek(self) -> bytes:
        return self.buff[self.index : self.index + 1]

    def read_bytes(self, length: int) -> bytes:
        if self.index + length <= len(self.buff):
            blob = self.buff[self.index : self.index + length]
            self.index += length
            return blob
        else:
            raise UnbencodeError("Short input")

    def read_int(self, stop: bytes) -> int:
        digits: list[bytes] = []
        while (d := self.getchar()) != stop:
            if not d.isdigit() and not (d == b"-" and not digits):
                raise UnbencodeError("Non-digit in integer")
            digits.append(d)
        num = b"".join(digits).decode("us-ascii")
        if not num or (num[0] == "0" and len(digits) > 1) or (num[0:2] == "-0"):
            raise UnbencodeError("Invalid bencoded integer")
        return int(num, 10)

    def get_trailing(self) -> bytes:
        return self.buff[self.index :]

    def decode_next(self) -> Any:
        c = self.getchar()
        if c == b"d":
            bdict: dict[bytes, Any] = {}
            prev_key: Optional[bytes] = None
            while self.peek() != b"e":
                key = self.decode_next()
                if not isinstance(key, bytes):
                    raise UnbencodeError("Non-bytes key in dict")
                elif prev_key is not None and key <= prev_key:
                    raise UnbencodeError("Dict keys not in sorted order")
                value = self.decode_next()
                bdict[key] = value
                prev_key = key
            self.getchar()
            return bdict
        elif c == b"l":
            blist: list = []
            while self.peek() != b"e":
                blist.append(self.decode_next())
            self.getchar()
            return blist
        elif c == b"i":
            return self.read_int(b"e")
        elif c.isdigit():
            self.index -= 1
            length = self.read_int(b":")
            return self.read_bytes(length)
        else:
            raise UnbencodeError("Invalid byte in input")


def unbencode(blob: bytes) -> Any:
    (value, trailing) = partial_unbencode(blob)
    if trailing:
        raise UnbencodeError("Input contains trailing bytes")
    return value


def partial_unbencode(blob: bytes) -> tuple[Any, bytes]:
    decoder = Unbencoder(blob)
    try:
        value = decoder.decode_next()
    except RecursionError:
        raise UnbencodeError("Too many nested structures")
    return (value, decoder.get_trailing())
