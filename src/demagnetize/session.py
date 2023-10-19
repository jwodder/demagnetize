from __future__ import annotations
from collections.abc import AsyncGenerator
from contextlib import aclosing
from typing import TYPE_CHECKING
from anyio import (
    CapacityLimiter,
    EndOfStream,
    Event,
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
from .util import TRACE, InfoHash, log

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
        # torf only accepts magnet links with valid info hashes, so this
        # shouldn't fail:
        self.info_hash = InfoHash.from_string(self.magnet.infohash)
        self.peer_limit = CapacityLimiter(PEERS_PER_MAGNET_LIMIT)

    async def get_info(self) -> dict:
        if not self.magnet.tr:
            raise DemagnetizeError(
                f"Cannot fetch info for info hash {self.info_hash}: No trackers"
                " in magnet link"
            )
        if self.magnet.dn is not None:
            display = f" ({self.magnet.dn})"
        else:
            display = ""
        log.info("Fetching info for info hash %s%s", self.info_hash, display)
        async with create_task_group() as tg:
            peer_aiter = self.get_all_peers(tg)
            info_sender, info_receiver = create_memory_object_stream[dict](0)
            tg.start_soon(self._peer_pipe, peer_aiter, info_sender, tg)
            async with info_receiver:
                try:
                    md = await info_receiver.receive()
                except EndOfStream:
                    raise DemagnetizeError(f"Failed to fetch info for {self.info_hash}")
            tg.cancel_scope.cancel()
            return md

    async def get_all_peers(self, task_group: TaskGroup) -> AsyncGenerator[Peer, None]:
        sender, receiver = create_memory_object_stream[Peer]()
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
                    log.log(TRACE, "%s returned by multiple trackers; skipping", p)

    async def _peer_pipe(
        self,
        peer_aiter: AsyncGenerator[Peer, None],
        info_sender: MemoryObjectSendStream[dict],
        task_group: TaskGroup,
    ) -> None:
        info_fetched = Event()
        async with aclosing(peer_aiter), info_sender:
            async for peer in peer_aiter:
                task_group.start_soon(
                    self._peer_task, peer, info_sender.clone(), info_fetched
                )

    async def _peer_task(
        self, peer: Peer, info_sender: MemoryObjectSendStream[dict], info_fetched: Event
    ) -> None:
        async with self.peer_limit, info_sender:
            if not info_fetched.is_set():
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
                    log.info("Received info for %s from %s", self.info_hash, peer)
                    info_fetched.set()
                    await info_sender.send(info)
