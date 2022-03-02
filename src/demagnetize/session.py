from __future__ import annotations
from typing import (
    TYPE_CHECKING,
    AsyncContextManager,
    AsyncIterator,
    Awaitable,
    Iterable,
    List,
)
from anyio import EndOfStream, create_memory_object_stream, create_task_group
from anyio.streams.memory import MemoryObjectSendStream
import attr
from torf import Magnet
from .bencode import unbencode
from .errors import DemagnetizeFailure, PeerError, TrackerError
from .peer import Peer
from .trackers import Tracker
from .util import InfoHash, InfoPiecer, acollectiter, log

if TYPE_CHECKING:
    from .core import Demagnetizer


@attr.define
class TorrentSession:
    app: Demagnetizer
    magnet: Magnet
    info_hash: InfoHash = attr.field(init=False)

    def __attrs_post_init__(self) -> None:
        # torf only accepts magnet URLs with valid info hashes, so this
        # shouldn't fail:
        self.info_hash = InfoHash.from_string(self.magnet.infohash)

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
            tg.start_soon(self.pipe_peers, self.get_all_peers(), info_sender)
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
        coros: List[Awaitable[Iterable[Peer]]] = []
        for url in self.magnet.tr:
            try:
                tracker = Tracker.from_url(url)
            except ValueError as e:
                log.warning("%s: Invalid tracker URL: %s", url, e)
            else:
                coros.append(self.get_peers_from_tracker(tracker))
        return acollectiter(coros)

    async def get_peers_from_tracker(self, tracker: Tracker) -> List[Peer]:
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

    async def pipe_peers(
        self,
        peer_receiver: AsyncContextManager[AsyncIterator[Peer]],
        info_sender: MemoryObjectSendStream[dict],
    ) -> None:
        async with peer_receiver as pait, info_sender:
            info_piecer = InfoPiecer()
            async for peer in pait:
                try:
                    await peer.get_info(self.app, self.info_hash, info_piecer)
                except PeerError as e:
                    log.warning(
                        "Error getting info for %s from %s: %s",
                        self.info_hash,
                        peer,
                        e.msg,
                    )
                log.info(
                    "Got %d info pieces from %s",
                    info_piecer.peer_contributions(peer),
                    peer,
                )
                if info_piecer.done:
                    log.info("All info pieces received")
                    blob = info_piecer.whole
                    ### TODO: Validate against info_hash
                    md = unbencode(blob)
                    ### TODO: Catch decode errors
                    await info_sender.send(md)
                    break
