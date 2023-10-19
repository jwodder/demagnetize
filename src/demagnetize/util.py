from __future__ import annotations
from base64 import b32decode
from collections.abc import AsyncIterator, Awaitable, Iterable, Iterator
from contextlib import AsyncExitStack, asynccontextmanager
from hashlib import sha1
import logging
from random import choices, randrange
import re
from string import ascii_letters, digits
from typing import Any, Optional, TypeVar, cast
from anyio import CapacityLimiter, create_memory_object_stream, create_task_group
from anyio.streams.memory import MemoryObjectSendStream
import attr
from torf import Magnet, Torrent
from .consts import INFO_CHUNK_SIZE, PEER_ID_PREFIX

log = logging.getLogger(__package__)

TRACE = 5

T = TypeVar("T")


@attr.define
class InfoHash:
    as_str: str = attr.field(eq=False)
    as_bytes: bytes

    @classmethod
    def from_string(cls, s: str) -> InfoHash:
        if len(s) == 40:
            b = bytes.fromhex(s)
        elif len(s) == 32:
            b = b32decode(s)
        else:
            raise ValueError(f"Invalid info hash: {s!r}")
        return cls(as_str=s, as_bytes=b)

    @classmethod
    def from_bytes(cls, b: bytes) -> InfoHash:
        if len(b) != 20:
            raise ValueError(f"Invalid info hash: {b!r}")
        return cls(as_str=b.hex(), as_bytes=b)

    def __str__(self) -> str:
        return self.as_str

    def __bytes__(self) -> bytes:
        return self.as_bytes

    @property
    def as_hex(self) -> str:
        return self.as_bytes.hex()


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
    #: Collection of magnet links and the files their torrents were saved to
    #: (None if the demagnetization failed)
    downloads: list[tuple[Magnet, Optional[str]]] = attr.Factory(list)

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


def template_torrent_filename(fntemplate: str, torrent: Torrent) -> str:
    fields = {
        "name": sanitize_pathname(str(torrent.name)),
        "hash": torrent.infohash,
    }
    return fntemplate.format_map(fields)


def sanitize_pathname(s: str) -> str:
    return re.sub(r'[\0-\x1F\x5C/<>:|"?*]', "_", re.sub(r"\s", " ", s))


def make_peer_id() -> bytes:
    s = PEER_ID_PREFIX.encode("utf-8")[:20]
    if len(s) < 20:
        s += "".join(choices(ascii_letters + digits, k=20 - len(s))).encode("us-ascii")
    return s


@asynccontextmanager
async def acollect(
    coros: Iterable[Awaitable[T]], limit: Optional[CapacityLimiter] = None
) -> AsyncIterator[AsyncIterator[T]]:
    async with create_task_group() as tg:
        sender, receiver = create_memory_object_stream[T]()
        async with sender:
            for c in coros:
                tg.start_soon(_acollect_pipe, c, limit, sender.clone())
        async with receiver:
            yield receiver


async def _acollect_pipe(
    coro: Awaitable[T],
    limit: Optional[CapacityLimiter],
    sender: MemoryObjectSendStream[T],
) -> None:
    async with AsyncExitStack() as stack:
        if limit is not None:
            await stack.enter_async_context(limit)
        await stack.enter_async_context(sender)
        value = await coro
        await sender.send(value)


@attr.define
class InfoPiecer:
    total_size: int
    data: bytearray = attr.Factory(bytearray)
    sizes: list[int] = attr.field(init=False)
    index: int = 0
    digest: Any = attr.Factory(sha1)

    def __attrs_post_init__(self) -> None:
        qty, residue = divmod(self.total_size, INFO_CHUNK_SIZE)
        self.sizes = [INFO_CHUNK_SIZE] * qty
        if residue:
            self.sizes.append(residue)

    @property
    def piece_qty(self) -> int:
        return len(self.sizes)

    def add_piece(self, blob: bytes) -> None:
        if self.index >= len(self.sizes):
            raise ValueError("Too many pieces")
        expected_len = self.sizes[self.index]
        if len(blob) != expected_len:
            raise ValueError(
                f"Piece {self.index} is wrong length: expected {expected_len}"
                f" bytes, got {len(blob)}"
            )
        self.data.extend(blob)
        self.digest.update(blob)
        self.index += 1

    def get_data(self) -> bytes:
        return bytes(self.data)

    def get_digest(self) -> str:
        return cast(str, self.digest.hexdigest())


def get_typed_value(data: dict[bytes, Any], key: bytes, klass: type[T]) -> Optional[T]:
    if isinstance(value := data.get(key), klass):
        return value
    else:
        return None


def get_string(data: dict[bytes, Any], key: bytes) -> Optional[str]:
    if isinstance(value := data.get(key), bytes):
        return value.decode("utf-8", "replace")
    else:
        return None
