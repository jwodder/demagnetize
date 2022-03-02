from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Optional, TextIO
import anyio
import click
from click_loglevel import LogLevel
from torf import Magnet
from .core import Demagnetizer
from .peer import Peer
from .trackers import Tracker
from .util import TRACE, InfoHash, log, yield_lines


def validate_template(
    _ctx: click.Context, _param: click.Parameter, value: Optional[str]
) -> Optional[str]:
    if value is not None:
        try:
            value.format(name="name", hash="hash")
        except ValueError:
            raise click.BadParameter(f"{value}: invalid filename template")
    return value


@click.group()
@click.option(
    "-l",
    "--log-level",
    type=LogLevel(extra={"TRACE": TRACE}),
    default=logging.INFO,
    help="Set logging level  [default: INFO]",
)
def main(log_level: int) -> None:
    logging.basicConfig(
        format="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        level=log_level,
    )
    logging.addLevelName(TRACE, "TRACE")


@main.command()
@click.option("-o", "--outfile", default="{name}.torrent", callback=validate_template)
@click.argument("magnet", type=Magnet.from_string)
@click.pass_context
def get(ctx: click.Context, magnet: Magnet, outfile: str) -> None:
    """Convert a magnet URL to a .torrent file"""
    demagnetizer = Demagnetizer()
    r = anyio.run(demagnetizer.demagnetize2file, magnet, outfile)
    if not r.ok:
        ctx.exit(1)


@main.command()
@click.option("-o", "--outfile", default="{name}.torrent", callback=validate_template)
@click.argument("magnetfile", type=click.File())
@click.pass_context
def batch(ctx: click.Context, magnetfile: TextIO, outfile: str) -> None:
    """Convert a collection of magnet URLs to .torrent files"""
    magnets: list[Magnet] = []
    ok = True
    with magnetfile:
        for line in yield_lines(magnetfile):
            try:
                m = Magnet.from_string(line)
            except ValueError:
                log.error("Invalid magnet URL: %s", line)
                ok = False
            else:
                magnets.append(m)
    if not magnets:
        log.info("No magnet URLs to fetch")
        ctx.exit(0 if ok else 1)
    demagnetizer = Demagnetizer()
    r = anyio.run(demagnetizer.download_torrent_info, magnets, outfile)
    log.info(
        "%d/%d magnet URLs successfully converted to torrent files", r.finished, r.total
    )
    if not r.ok:
        ctx.exit(1)


@main.command()
@click.argument("tracker", type=Tracker.from_url)
@click.argument("infohash", type=InfoHash.from_string)
def get_peers(tracker: Tracker, infohash: InfoHash) -> None:
    demagnetizer = Demagnetizer()
    peers = anyio.run(demagnetizer.get_peers_from_tracker, tracker, infohash)
    for p in peers:
        print(json.dumps(p.for_json()))


@main.command()
@click.argument("host")
@click.argument("port", type=int)
@click.argument("infohash", type=InfoHash.from_string)
def get_info_from_peer(host: str, port: int, infohash: InfoHash) -> None:
    demagnetizer = Demagnetizer()
    peer = Peer(host=host, port=port)
    info = anyio.run(demagnetizer.get_info_from_peer, peer, infohash)
    p = Path(f"{infohash}.bencode")
    log.info("Saving info to %s", p)
    p.write_bytes(info)


@main.command()
@click.argument("magnet", type=Magnet.from_string)
@click.pass_context
def get_magnet_peers(ctx: click.Context, magnet: Magnet) -> None:
    demagnetizer = Demagnetizer()

    async def aprint_magnet_peers() -> bool:
        ok = False
        async with demagnetizer.get_peers_for_magnet(magnet) as ait:
            async for p in ait:
                ok = True
                print(json.dumps(p.for_json()))
        return ok

    if not anyio.run(aprint_magnet_peers):
        ctx.exit(1)


if __name__ == "__main__":
    main()
