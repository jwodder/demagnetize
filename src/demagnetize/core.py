from dataclasses import dataclass, field
from functools import partial
from random import randint
from time import time
from typing import Awaitable, Callable, List, Union
from anyio import EndOfStream, create_memory_object_stream, create_task_group
from anyio.abc import TaskGroup
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from torf import Magnet, Torrent
from yarl import URL
from .consts import CLIENT
from .errors import DemagnetizeFailure, Error, TrackerError
from .peers import Peer
from .trackers import HTTPTracker, Tracker, UDPTracker
from .util import (
    InfoHash,
    Key,
    Report,
    acollect,
    log,
    make_peer_id,
    template_torrent_filename,
)


@dataclass
class Demagnetizer:
    peer_id: bytes = field(default_factory=make_peer_id)
    peer_port: int = field(default_factory=lambda: randint(1025, 65535))

    async def download_torrents(
        self,
        magnets: List[Union[str, Magnet]],
        outfile_pattern: str,
    ) -> Report:
        funcs: List[Callable[[], Awaitable[Report]]] = []
        for m in magnets:
            if not isinstance(m, Magnet):
                try:
                    m = Magnet.from_string(m)
                except ValueError:
                    log.error("Invalid magnet URL: %s", m)
                    continue
            funcs.append(partial(self.demagnetize2file, m, outfile_pattern))
        report = Report()
        if funcs:
            async with acollect(funcs) as ait:
                async for r in ait:
                    report += r
        return report

    async def demagnetize2file(self, magnet: Magnet, pattern: str) -> Report:
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
            return Report.for_failure(magnet)
        else:
            return Report.for_success(magnet, filename)

    async def demagnetize(self, magnet: Magnet) -> Torrent:
        # torf only accepts magnet URLs with valid info hashes, so this
        # shouldn't fail:
        info_hash = InfoHash.from_string(magnet.infohash)
        if not magnet.tr:
            raise DemagnetizeFailure(
                f"Cannot fetch info for info hash {info_hash}: No trackers in"
                " magnet URL"
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
            info_sender, info_receiver = create_memory_object_stream()
            tg.start_soon(self.pipe_peers, info_hash, tg, peer_receiver, info_sender)
            async with info_receiver:
                try:
                    md = await info_receiver.receive()
                except EndOfStream:
                    raise DemagnetizeFailure(
                        f"Could not fetch info for info hash {info_hash}"
                    )
            tg.cancel_scope.cancel()
        return compose_torrent(magnet, md)

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
        info_sender: MemoryObjectSendStream[dict],
    ) -> None:
        async with peer_receiver, info_sender:
            async for peer in peer_receiver:
                task_group.start_soon(
                    self.get_info_from_peer,
                    peer,
                    info_hash,
                    info_sender.clone(),
                )

    async def get_info_from_peer(
        self, peer: Peer, info_hash: InfoHash, sender: MemoryObjectSendStream[dict]
    ) -> None:
        async with sender:
            try:
                md = await peer.get_info(info_hash)
                await sender.send(md)
            except Error as e:
                log.warning(
                    "Error getting info for %s from %s: %s",
                    info_hash,
                    peer,
                    e,
                )

    def get_tracker(self, url: str) -> Tracker:
        try:
            u = URL(url)
        except ValueError:
            raise TrackerError("Invalid tracker URL")
        if u.scheme in ("http", "https"):
            return HTTPTracker(url=u, peer_id=self.peer_id, peer_port=self.peer_port)
        elif u.scheme == "udp":
            try:
                return UDPTracker(
                    url=u,
                    peer_id=self.peer_id,
                    peer_port=self.peer_port,
                    key=Key.generate(),
                )
            except ValueError as e:
                raise TrackerError(f"Invalid tracker URL: {e}")
        else:
            raise TrackerError(f"Unsupported URL scheme {u.scheme!r}")


def compose_torrent(magnet: Magnet, info: dict) -> Torrent:
    torrent = Torrent()
    torrent.metadata["info"] = info
    torrent.trackers = magnet.tr
    torrent.created_by = CLIENT
    torrent.creation_date = time()
    return torrent
