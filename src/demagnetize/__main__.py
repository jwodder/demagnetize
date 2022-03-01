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
    with magnetfile:
        magnets = list(yield_lines(magnetfile))
    if not magnets:
        log.info("No magnet URLs to fetch")
        return
    demagnetizer = Demagnetizer()
    r = anyio.run(demagnetizer.download_torrent_info, magnets, outfile)
    log.info(
        "%d/%d magnet URLs successfully converted to torrent files", r.finished, r.total
    )
    if not r.ok:
        ctx.exit(1)


@main.command()
@click.argument("tracker")
@click.argument("infohash", type=InfoHash.from_string)
def get_peers(tracker: str, infohash: InfoHash) -> None:
    demagnetizer = Demagnetizer()
    peers = anyio.run(demagnetizer.get_peers, tracker, infohash)
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


if __name__ == "__main__":
    main()
