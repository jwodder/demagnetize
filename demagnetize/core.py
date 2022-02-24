import logging
from typing import Optional, Union
from anyio import create_task_group, create_memory_object_stream, EndOfStream, TaskGroup
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from torf import Magnet, Torrent
from .errors import DemagnetizeFailure, Error
from .peers import Peer
from .trackers import get_tracker
from .util import InfoHash

log = logging.getLogger(__package__)


async def demagnetize(
    magnet: Union[str, Magnet],
    peer_id: Optional[str] = None,
    peer_port: Optional[int] = None,
) -> Torrent:
    if not isinstance(magnet, Magnet):
        magnet = Magnet.from_string(magnet_url)
    if not magnet.tr:
        raise ValueError("No trackers in magnet URL")
    info_hash = InfoHash.from_string(magnet.infohash)
    if peer_id is None:
        raise NotImplementedError
    if peer_port is None:
        raise NotImplementedError
    async with create_task_group() as tg:
        peer_sender, peer_receiver = create_memory_object_stream()
        async with peer_sender:
            for tr_url in magnet.tr:
                tg.start_soon(
                    get_peers_from_tracker,
                    tr_url,
                    peer_id,
                    peer_port,
                    info_hash,
                    peer_sender.clone(),
                )
        metadata_sender, metadata_receiver = create_memory_object_stream()
        tg.start_soon(pipe_peers, info_hash, tg, peer_receiver, metadata_sender)
        async with metadata_receiver:
            try:
                md = await metadata_receiver.receive()
            except EndOfStream:
                raise DemagnetizeFailure(
                    f"Could not fetch metadata for info hash {info_hash}"
                )
        tg.cancel_scope.cancel()
    torrent = Torrent()
    torrent.metadata["info"] = md
    torrent.trackers = magnet.tr
    return torrent


async def get_peers_from_tracker(
    url: str,
    peer_id: str,
    peer_port: int,
    info_hash: InfoHash,
    sender: MemoryObjectSendStream[Peer],
) -> None:
    async with sender:
        try:
            tracker = get_tracker(url)
            log.info("Requesting peers for %s from tracker at %s", info_hash, url)
            peers = await tracker.get_peers(bytes(info_hash))
            for p in peers:
                sender.send(p)
        except Error as e:
            log.warning(
                "Error getting peers for %s from tracker at %s: %s",
                info_hash,
                url,
                e,
            )


async def pipe_peers(
    info_hash: InfoHash,
    task_group: TaskGroup,
    peer_receiver: MemoryObjectReceiveStream[Peer],
    metadata_sender: MemoryObjectSendStream[dict],
) -> None:
    async with peer_receiver, metadata_sender:
        async for peer in peer_receiver:
            task_group.start_soon(
                get_metadata_from_peer, peer, info_hash, metadata_sender.clone()
            )


async def get_metadata_from_peer(
    peer: Peer, info_hash: InfoHash, sender: MemoryObjectSendStream[dict]
) -> None:
    async with sender:
        try:
            log.info("Requesting metadata for %s from peer %s", info_hash, peer)
            async with await peer.connect() as connpeer:
                md = await connpeer.get_metadata(bytes(info_hash))
            sender.send(md)
        except Error as e:
            log.warning(
                "Error getting metadata for %s from peer %s: %s",
                info_hash,
                peer,
                e,
            )
