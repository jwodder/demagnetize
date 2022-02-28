from __future__ import annotations
from typing import TYPE_CHECKING
from anyio import EndOfStream, create_memory_object_stream, create_task_group
from anyio.abc import TaskGroup
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
import attr
from torf import Magnet
from .errors import DemagnetizeFailure, Error
from .peer import Peer
from .trackers import Tracker
from .util import InfoHash, log

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
            peer_sender, peer_receiver = create_memory_object_stream()
            async with peer_sender:
                for tr_url in self.magnet.tr:
                    tg.start_soon(
                        self.get_peers_from_tracker,
                        tr_url,
                        peer_sender.clone(),
                    )
            info_sender, info_receiver = create_memory_object_stream(0, item_type=dict)
            tg.start_soon(self.pipe_peers, tg, peer_receiver, info_sender)
            async with info_receiver:
                try:
                    md = await info_receiver.receive()
                except EndOfStream:
                    raise DemagnetizeFailure(
                        f"Could not fetch info for info hash {self.info_hash}"
                    )
            tg.cancel_scope.cancel()
            return md

    async def get_peers_from_tracker(
        self, url: str, sender: MemoryObjectSendStream[Peer]
    ) -> None:
        async with sender:
            try:
                tracker = Tracker.from_url(url)
                peers = await tracker.get_peers(self.app, self.info_hash)
                for p in peers:
                    await sender.send(p)
            except Error as e:
                log.warning(
                    "Error getting peers for %s from tracker at %s: %s",
                    self.info_hash,
                    url,
                    e,
                )

    async def pipe_peers(
        self,
        task_group: TaskGroup,
        peer_receiver: MemoryObjectReceiveStream[Peer],
        info_sender: MemoryObjectSendStream[dict],
    ) -> None:
        async with peer_receiver, info_sender:
            async for peer in peer_receiver:
                task_group.start_soon(
                    self.get_info_from_peer, peer, info_sender.clone()
                )

    async def get_info_from_peer(
        self, peer: Peer, sender: MemoryObjectSendStream[dict]
    ) -> None:
        async with sender:
            try:
                md = await peer.get_info(self.info_hash)
                await sender.send(md)
            except Error as e:
                log.warning(
                    "Error getting info for %s from %s: %s", self.info_hash, peer, e
                )
