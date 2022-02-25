import logging
from typing import List, Optional, TextIO, Tuple
import anyio
import click
from click_loglevel import LogLevel
from torf import Magnet
from .core import Demagnetizer
from .util import log, yield_lines


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
    type=LogLevel(),
    default=logging.INFO,
    help="Set logging level  [default: INFO]",
)
def main(log_level: int) -> None:
    logging.basicConfig(
        format="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        level=log_level,
    )


@main.command()
@click.option("-o", "--outfile", default="{name}.torrent", callback=validate_template)
@click.argument("magnet", type=Magnet.from_string)
@click.pass_context
def get(ctx: click.Context, magnet: Magnet, outfile: str) -> None:
    """Convert a magnet URL to a .torrent file"""
    demagnetizer = Demagnetizer()
    output: List[Tuple[Magnet, Optional[str]]] = []
    anyio.run(demagnetizer.demagnetize2file, magnet, outfile, output)
    downloaded = sum(1 for _, fname in output if fname is not None)
    if not downloaded or downloaded < len(output):
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
    r = anyio.run(demagnetizer.download_torrents, magnets, outfile)
    downloaded = sum(1 for _, fname in r if fname is not None)
    log.info(
        "%d/%d magnet URLs successfully converted to torrent files", downloaded, len(r)
    )
    if not downloaded or downloaded < len(r):
        ctx.exit(1)


if __name__ == "__main__":
    main()
