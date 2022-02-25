from dataclasses import dataclass, field
from random import randint
from typing import List, Optional, Tuple, Union
from anyio import EndOfStream, TaskGroup, create_memory_object_stream, create_task_group
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from torf import Magnet, Torrent
from .errors import DemagnetizeFailure, Error
from .peers import Peer
from .trackers import Tracker
from .util import InfoHash, log, make_peer_id, template_torrent_filename


@dataclass
class Demagnetizer:
    peer_id: str = field(default_factory=make_peer_id)
    peer_port: int = field(default_factory=lambda: randint(1025, 65535))

    async def download_torrents(
        self,
        magnets: List[Union[str, Magnet]],
        outfile_pattern: str,
    ) -> List[Tuple[Magnet, Optional[str]]]:
        output: List[Tuple[Magnet, Optional[str]]] = []
        async with create_task_group() as tg:
            for m in magnets:
                try:
                    if not isinstance(m, Magnet):
                        m = Magnet.from_string(m)
                except ValueError:
                    log.error("Invalid magnet URL: %s", m)
                    continue
                tg.start_soon(self.demagnetize2file, m, outfile_pattern, output)
        return output

    async def demagnetize2file(
        self, magnet: Magnet, pattern: str, output: List[Tuple[[Magnet, Optional[str]]]]
    ) -> None:
        try:
            torrent = await self.demagnetize(magnet)
            filename = template_torrent_filename(pattern, torrent)
            log.info(
                "Saving torrent for info hash %s to file %s", magnet.infohash, filename
            )
            ### TODO: Catch write errors?
            torrent.write(filename)
        except DemagnetizeFailure as e:
            log.error("%s", e)
            output.append(magnet, None)
        else:
            output.append(magnet, filename)

    async def demagnetize(self, magnet: Magnet) -> Torrent:
        # torf only accepts magnet URLs with valid info hashes, so this
        # shouldn't fail:
        info_hash = InfoHash.from_string(magnet.infohash)
        if not magnet.tr:
            raise DemagnetizeFailure(
                f"Cannot fetch metadata for info hash {info_hash}: No trackers"
                " in magnet URL"
            )
        async with create_task_group() as tg:
            peer_sender, peer_receiver = create_memory_object_stream()
            async with peer_sender:
                for tr_url in magnet.tr:
                    tg.start_soon(
                        self.get_peers_from_tracker,
                        tr_url,
                        info_hash,
                        peer_sender.clone(),
                    )
            metadata_sender, metadata_receiver = create_memory_object_stream()
            tg.start_soon(
                self.pipe_peers, info_hash, tg, peer_receiver, metadata_sender
            )
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
        self,
        url: str,
        info_hash: InfoHash,
        sender: MemoryObjectSendStream[Peer],
    ) -> None:
        async with sender:
            try:
                tracker = self.get_tracker(url)
                peers = await tracker.get_peers(info_hash)
                for p in peers:
                    await sender.send(p)
            except Error as e:
                log.warning(
                    "Error getting peers for %s from tracker at %s: %s",
                    info_hash,
                    url,
                    e,
                )

    async def pipe_peers(
        self,
        info_hash: InfoHash,
        task_group: TaskGroup,
        peer_receiver: MemoryObjectReceiveStream[Peer],
        metadata_sender: MemoryObjectSendStream[dict],
    ) -> None:
        async with peer_receiver, metadata_sender:
            async for peer in peer_receiver:
                task_group.start_soon(
                    self.get_metadata_from_peer,
                    peer,
                    info_hash,
                    metadata_sender.clone(),
                )

    async def get_metadata_from_peer(
        self, peer: Peer, info_hash: InfoHash, sender: MemoryObjectSendStream[dict]
    ) -> None:
        async with sender:
            try:
                md = await peer.get_metadata(info_hash)
                await sender.send(md)
            except Error as e:
                log.warning(
                    "Error getting metadata for %s from peer %s: %s",
                    info_hash,
                    peer,
                    e,
                )

    def get_tracker(self, url: str) -> Tracker:
        raise NotImplementedError
