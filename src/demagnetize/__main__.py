from typing import TextIO
import anyio
import click
from .core import Demagnetizer
from .util import log, yield_lines


@click.command()
@click.option("-o", "--outfile", default="{name}.torrent")
### TODO: Validate that `outfile` is a valid placeholder string
### TODO: Add options for setting peer ID & port
@click.option("magnetfile", type=click.File())
@click.pass_context
def main(ctx: click.Context, magnetfile: TextIO, outfile: str) -> None:
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
