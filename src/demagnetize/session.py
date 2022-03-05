from __future__ import annotations
import sys
from typing import TYPE_CHECKING, AsyncIterator
from anyio import (
    CapacityLimiter,
    EndOfStream,
    create_memory_object_stream,
    create_task_group,
)
from anyio.abc import TaskGroup
from anyio.streams.memory import MemoryObjectSendStream
import attr
from torf import Magnet
from .consts import PEERS_PER_MAGNET_LIMIT
from .errors import DemagnetizeError, PeerError
from .peer import Peer, PeerAddress
from .trackers import Tracker
from .util import InfoHash, log

if sys.version_info >= (3, 10):
    from contextlib import aclosing
else:
    from async_generator import aclosing

if TYPE_CHECKING:
    from .core import Demagnetizer


@attr.define
class TorrentSession:
    app: Demagnetizer
    magnet: Magnet
    info_hash: InfoHash = attr.field(init=False)
    peer_limit: CapacityLimiter = attr.field(init=False)
    peers_seen: set[PeerAddress] = attr.Factory(set)

    def __attrs_post_init__(self) -> None:
        # torf only accepts magnet URLs with valid info hashes, so this
        # shouldn't fail:
        self.info_hash = InfoHash.from_string(self.magnet.infohash)
        self.peer_limit = CapacityLimiter(PEERS_PER_MAGNET_LIMIT)

    async def get_info(self) -> dict:
        if not self.magnet.tr:
            raise DemagnetizeError(
                f"Cannot fetch info for info hash {self.info_hash}: No trackers"
                " in magnet URL"
            )
        if self.magnet.dn is not None:
            display = f" ({self.magnet.dn})"
        else:
            display = ""
        log.info("Fetching info for info hash %s%s", self.info_hash, display)
        async with create_task_group() as tg:
            peer_aiter = self.get_all_peers(tg)
            info_sender, info_receiver = create_memory_object_stream(0, dict)
            tg.start_soon(self._peer_pipe, peer_aiter, info_sender, tg)
            async with info_receiver:
                try:
                    md = await info_receiver.receive()
                except EndOfStream:
                    raise DemagnetizeError(f"Failed to fetch info for {self.info_hash}")
            tg.cancel_scope.cancel()
            return md

    async def get_all_peers(self, task_group: TaskGroup) -> AsyncIterator[Peer]:
        sender, receiver = create_memory_object_stream()
        async with sender:
            for url in self.magnet.tr:
                try:
                    tracker = Tracker.from_url(url)
                except ValueError as e:
                    log.warning("%s: Invalid tracker URL: %s", url, e)
                else:
                    task_group.start_soon(
                        tracker.get_peers, self.app, self.info_hash, sender.clone()
                    )
        async with receiver:
            async for p in receiver:
                if (addr := p.address) not in self.peers_seen:
                    self.peers_seen.add(addr)
                    yield p
                else:
                    log.debug("%s returned by multiple trackers; skipping", p)

    async def _peer_pipe(
        self,
        peer_aiter: AsyncIterator[Peer],
        info_sender: MemoryObjectSendStream[dict],
        task_group: TaskGroup,
    ) -> None:
        async with aclosing(peer_aiter), info_sender:
            async for peer in peer_aiter:
                task_group.start_soon(self._peer_task, peer, info_sender.clone())

    async def _peer_task(
        self, peer: Peer, info_sender: MemoryObjectSendStream[dict]
    ) -> None:
        async with self.peer_limit, info_sender:
            try:
                info = await peer.get_info(self.app, self.info_hash)
            except PeerError as e:
                log.warning(
                    "Error getting info for %s from %s: %s",
                    self.info_hash,
                    peer,
                    e.msg,
                )
            else:
                log.info("Received info from %s", peer)
                await info_sender.send(info)
