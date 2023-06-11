from __future__ import annotations
from pathlib import Path
from random import randint
from time import time
from anyio import CapacityLimiter
import attr
import click
from torf import Magnet, Torrent
from torf._utils import decode_dict
from .consts import CLIENT, MAGNET_LIMIT
from .errors import DemagnetizeError
from .session import TorrentSession
from .util import Key, Report, acollect, log, make_peer_id, template_torrent_filename


@attr.define
class Demagnetizer:
    key: Key = attr.Factory(Key.generate)
    peer_id: bytes = attr.Factory(make_peer_id)
    peer_port: int = attr.Factory(lambda: randint(1025, 65535))

    def __attrs_post_init__(self) -> None:
        log.debug("Using key = %s", self.key)
        log.debug("Using peer ID = %r", self.peer_id)
        log.debug("Using peer port = %d", self.peer_port)

    async def download_torrent_info(
        self, magnets: list[Magnet], fntemplate: str
    ) -> Report:
        report = Report()
        coros = [self.demagnetize2file(m, fntemplate) for m in magnets]
        async with acollect(coros, limit=CapacityLimiter(MAGNET_LIMIT)) as ait:
            async for r in ait:
                report += r
        return report

    async def demagnetize2file(self, magnet: Magnet, fntemplate: str) -> Report:
        try:
            torrent = await self.demagnetize(magnet)
            filename = template_torrent_filename(fntemplate, torrent)
            log.info(
                "Saving torrent for info hash %s to file %s", magnet.infohash, filename
            )
        except DemagnetizeError as e:
            log.error("%s", e)
            return Report.for_failure(magnet)
        try:
            Path(filename).parent.mkdir(parents=True, exist_ok=True)
            with click.open_file(filename, "wb") as fp:
                torrent.write_stream(fp)
        except Exception as e:
            log.error(
                "Error writing torrent to file %r: %s: %s",
                filename,
                type(e).__name__,
                e,
            )
            return Report.for_failure(magnet)
        return Report.for_success(magnet, filename)

    async def demagnetize(self, magnet: Magnet) -> Torrent:
        session = self.open_session(magnet)
        md = await session.get_info()
        return compose_torrent(magnet, md)

    def open_session(self, magnet: Magnet) -> TorrentSession:
        return TorrentSession(app=self, magnet=magnet)


def compose_torrent(magnet: Magnet, info: dict) -> Torrent:
    torrent = Torrent()
    torrent.metainfo["info"] = decode_dict(info)
    torrent.trackers = magnet.tr
    torrent.created_by = CLIENT
    torrent.creation_date = time()
    return torrent
