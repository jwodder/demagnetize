from __future__ import annotations
from typing import (
    TYPE_CHECKING,
    AsyncContextManager,
    AsyncIterator,
    Awaitable,
    Iterable,
)
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
from .errors import DemagnetizeFailure, PeerError, TrackerError
from .peer import Peer
from .trackers import Tracker
from .util import InfoHash, acollectiter, log

if TYPE_CHECKING:
    from .core import Demagnetizer


@attr.define
class TorrentSession:
    app: Demagnetizer
    magnet: Magnet
    info_hash: InfoHash = attr.field(init=False)
    peer_limit: CapacityLimiter = attr.field(init=False)

    def __attrs_post_init__(self) -> None:
        # torf only accepts magnet URLs with valid info hashes, so this
        # shouldn't fail:
        self.info_hash = InfoHash.from_string(self.magnet.infohash)
        self.peer_limit = CapacityLimiter(PEERS_PER_MAGNET_LIMIT)

    async def get_info(self) -> dict:
        if not self.magnet.tr:
            raise DemagnetizeFailure(
                f"Cannot fetch info for info hash {self.info_hash}: No trackers"
                " in magnet URL"
            )
        if self.magnet.dn is not None:
            display = f" ({self.magnet.dn})"
        else:
            display = ""
        log.info("Fetching info for info hash %s%s", self.info_hash, display)
        async with create_task_group() as tg:
            info_sender, info_receiver = create_memory_object_stream(0, dict)
            tg.start_soon(self._peer_pipe, self.get_all_peers(), info_sender)
            async with info_receiver:
                try:
                    md = await info_receiver.receive()
                except EndOfStream:
                    raise DemagnetizeFailure(
                        f"Failed to fetch info for {self.info_hash}"
                    )
            tg.cancel_scope.cancel()
            return md

    def get_all_peers(self) -> AsyncContextManager[AsyncIterator[Peer]]:
        coros: list[Awaitable[Iterable[Peer]]] = []
        for url in self.magnet.tr:
            try:
                tracker = Tracker.from_url(url)
            except ValueError as e:
                log.warning("%s: Invalid tracker URL: %s", url, e)
            else:
                coros.append(self.get_peers_from_tracker(tracker))
        return acollectiter(coros)

    async def get_peers_from_tracker(self, tracker: Tracker) -> list[Peer]:
        try:
            return await tracker.get_peers(self.app, self.info_hash)
        except TrackerError as e:
            log.warning(
                "Error getting peers for %s from %s: %s",
                self.info_hash,
                tracker,
                e.msg,
            )
            return []

    async def _peer_pipe(
        self,
        peer_receiver: AsyncContextManager[AsyncIterator[Peer]],
        info_sender: MemoryObjectSendStream[dict],
        task_group: TaskGroup,
    ) -> None:
        async with peer_receiver as pait, info_sender:
            async for peer in pait:
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
