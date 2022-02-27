from __future__ import annotations
from base64 import b32decode
from binascii import unhexlify
from contextlib import asynccontextmanager
import logging
from random import choices, randrange
import re
from string import ascii_letters, digits
from typing import (
    AsyncIterator,
    Awaitable,
    Callable,
    Iterable,
    Iterator,
    List,
    Optional,
    Tuple,
    TypeVar,
)
from anyio import create_memory_object_stream, create_task_group
from anyio.streams.memory import MemoryObjectSendStream
import attr
from torf import Magnet, Torrent
from .consts import PEER_ID_PREFIX

log = logging.getLogger(__package__)

TRACE = 5

T = TypeVar("T")


@attr.define
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


@attr.define
class Key:
    value: int

    @classmethod
    def generate(cls) -> Key:
        return cls(randrange(1 << 32))

    def __int__(self) -> int:
        return self.value

    def __str__(self) -> str:
        return f"{self.value:08x}"

    def __bytes__(self) -> bytes:
        return self.value.to_bytes(4, "big")


@attr.define
class Report:
    #: Collection of magnet URLs and the files their torrents were saved to
    #: (None if the demagnetization failed)
    downloads: List[Tuple[Magnet, Optional[str]]] = attr.Factory(list)

    @classmethod
    def for_success(cls, magnet: Magnet, filename: str) -> Report:
        return cls(downloads=[(magnet, filename)])

    @classmethod
    def for_failure(cls, magnet: Magnet) -> Report:
        return cls(downloads=[(magnet, None)])

    @property
    def total(self) -> int:
        return len(self.downloads)

    @property
    def finished(self) -> int:
        return sum(1 for _, fname in self.downloads if fname is not None)

    @property
    def ok(self) -> bool:
        return bool(self.downloads) and all(
            fname is not None for _, fname in self.downloads
        )

    def __add__(self, other: Report) -> Report:
        return type(self)(self.downloads + other.downloads)

    def __iadd__(self, other: Report) -> Report:
        self.downloads.extend(other.downloads)
        return self


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


def make_peer_id() -> bytes:
    s = PEER_ID_PREFIX.encode("utf-8")[:20]
    if len(s) < 20:
        s += "".join(choices(ascii_letters + digits, k=20 - len(s))).encode("us-ascii")
    return s


@asynccontextmanager
async def acollect(
    funcs: Iterable[Callable[[], Awaitable[T]]]
) -> AsyncIterator[AsyncIterator[T]]:
    async with create_task_group() as tg:
        sender, receiver = create_memory_object_stream()
        async with sender:
            for f in funcs:
                tg.start_soon(_acollect_pipe, f, sender.clone())
        async with receiver:
            yield receiver


async def _acollect_pipe(
    func: Callable[[], Awaitable[T]], sender: MemoryObjectSendStream[T]
) -> None:
    async with sender:
        value = await func()
        await sender.send(value)
