from __future__ import annotations
import logging
import sys
from typing import Optional, TextIO
import anyio
import click
from click_loglevel import LogLevel
import colorlog
from torf import Magnet
from .core import Demagnetizer
from .util import TRACE, log, yield_lines


def validate_template(
    _ctx: click.Context, _param: click.Parameter, value: Optional[str]
) -> Optional[str]:
    if value is not None:
        try:
            value.format(name="name", hash="hash")
        except ValueError:
            raise click.BadParameter(f"{value}: invalid filename template")
    return value


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.option(
    "-l",
    "--log-level",
    type=LogLevel(extra={"TRACE": TRACE}),
    default="INFO",
    help="Set logging level",
    show_default=True,
)
def main(log_level: int) -> None:
    log.setLevel(log_level)
    colorlog.basicConfig(
        format="%(log_color)s%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        log_colors={
            "TRACE": "green",
            "DEBUG": "cyan",
            "INFO": "bold",
            "WARNING": "yellow",
            "ERROR": "red",
            "CRITICAL": "bold_red",
        },
        level="INFO",
        stream=sys.stderr,
    )
    logging.addLevelName(TRACE, "TRACE")


@main.command()
@click.option("-o", "--outfile", default="{name}.torrent", callback=validate_template)
@click.argument("magnet", type=Magnet.from_string)
@click.pass_context
def get(ctx: click.Context, magnet: Magnet, outfile: str) -> None:
    """Convert a magnet link to a .torrent file"""
    demagnetizer = Demagnetizer()
    r = anyio.run(demagnetizer.demagnetize2file, magnet, outfile)
    if not r.ok:
        ctx.exit(1)


@main.command()
@click.option("-o", "--outfile", default="{name}.torrent", callback=validate_template)
@click.argument("magnetfile", type=click.File())
@click.pass_context
def batch(ctx: click.Context, magnetfile: TextIO, outfile: str) -> None:
    """Convert a collection of magnet links to .torrent files"""
    magnets: list[Magnet] = []
    ok = True
    with magnetfile:
        for line in yield_lines(magnetfile):
            try:
                m = Magnet.from_string(line)
            except ValueError:
                log.error("Invalid magnet link: %s", line)
                ok = False
            else:
                magnets.append(m)
    if not magnets:
        log.info("No magnet links to fetch")
        ctx.exit(0 if ok else 1)
    demagnetizer = Demagnetizer()
    r = anyio.run(demagnetizer.download_torrent_info, magnets, outfile)
    log.info(
        "%d/%d magnet links successfully converted to torrent files",
        r.finished,
        r.total,
    )
    if not r.ok:
        ctx.exit(1)


if __name__ == "__main__":
    main()
