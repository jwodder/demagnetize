from __future__ import annotations
from dataclasses import dataclass
from binascii import unhexlify
from base64 import b32decode
import re
from typing import Iterable, Iterator
from torf import Torrent


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


def yield_lines(fp: Iterable[str]) -> Iterator[str]:
    for line in fp:
        line = line.strip()
        if line and not line.startswith("#"):
            yield line


def template_torrent_filename(pattern: str, torrent: Torrent) -> str:
    fields = {
        "name": sanitize_pathname(str(torrent.name)),
        "hash": torrent.infohash,
    }
    return pattern.format_map(fields)


def sanitize_pathname(s: str) -> str:
    return re.sub(r'[\0\x5C/<>:|"?*%]', "_", re.sub(r"\s", " ", s))


def make_peer_id() -> str:
    raise NotImplementedError
