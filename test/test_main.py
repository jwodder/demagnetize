from __future__ import annotations
from pathlib import Path
from traceback import format_exception
from click.testing import CliRunner, Result
import pytest
from torf import Torrent
from demagnetize.__main__ import main


def show_result(r: Result) -> str:
    if r.exception is not None:
        assert isinstance(r.exc_info, tuple)
        return "".join(format_exception(*r.exc_info))
    else:
        return r.output


@pytest.mark.parametrize(
    "magnet,infohash,trackers",
    [
        pytest.param(
            (
                "magnet:?xt=urn:btih:63a04291a8b266d968aa7ab8a276543fa63a9e84"
                "&dn=libgen-rs-r_000"
                "&tr=http%3A%2F%2Ftracker.opentrackr.org%3A1337%2Fannounce"
                "&tr=http%3A%2F%2Fopen.acgnxtracker.com%3A80%2Fannounce"
                "&tr=http%3A%2F%2Ftracker.bt4g.com%3A2095%2Fannounce"
                "&tr=http%3A%2F%2Ftracker.files.fm%3A6969%2Fannounce"
                "&tr=http%3A%2F%2Ftracker.gbitt.info%2Fannounce"
                "&tr=udp%3A%2F%2Ftracker.opentrackr.org%3A1337%2Fannounce"
                "&tr=udp%3A%2F%2Fexodus.desync.com%3A6969%2Fannounce"
                "&tr=udp%3A%2F%2Fipv4.tracker.harry.lu%3A80%2Fannounce"
                "&tr=udp%3A%2F%2Fopen.stealth.si%3A80%2Fannounce"
                "&tr=udp%3A%2F%2Ftracker.coppersurfer.tk%3A6969%2Fannounce"
            ),
            "63a04291a8b266d968aa7ab8a276543fa63a9e84",
            [
                "http://tracker.opentrackr.org:1337/announce",
                "http://open.acgnxtracker.com:80/announce",
                "http://tracker.bt4g.com:2095/announce",
                "http://tracker.files.fm:6969/announce",
                "http://tracker.gbitt.info/announce",
                "udp://tracker.opentrackr.org:1337/announce",
                "udp://exodus.desync.com:6969/announce",
                "udp://ipv4.tracker.harry.lu:80/announce",
                "udp://open.stealth.si:80/announce",
                "udp://tracker.coppersurfer.tk:6969/announce",
            ],
            id="http_udp",
        ),
        pytest.param(
            (
                "magnet:?xt=urn:btih:b851474b74f65cd19f981c723590e3e520242b97"
                "&dn=debian-12.0.0-amd64-netinst.iso"
                "&tr=http%3A%2F%2Fbttracker.debian.org%3A6969%2Fannounce"
                "&ws=https%3A%2F%2Fcdimage.debian.org%2Fcdimage%2Frelease%2F12.0.0%2Famd64%2Fiso-cd%2Fdebian-12.0.0-amd64-netinst.iso"
                "&ws=https%3A%2F%2Fcdimage.debian.org%2Fcdimage%2Farchive%2F12.0.0%2Famd64%2Fiso-cd%2Fdebian-12.0.0-amd64-netinst.iso"
            ),
            "b851474b74f65cd19f981c723590e3e520242b97",
            ["http://bttracker.debian.org:6969/announce"],
            id="multipiece",
        ),
    ],
)
def test_get(magnet: str, infohash: str, trackers: list[str]) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        r = runner.invoke(
            main,
            ["-l", "DEBUG", "get", "-o", "{hash}.torrent", magnet],
            standalone_mode=False,
        )
        assert r.exit_code == 0, show_result(r)
        p = Path(f"{infohash}.torrent")
        assert p.exists()
        t = Torrent.read(p)
        assert t.infohash == infohash
        assert t.created_by is not None
        assert t.created_by.startswith("demagnetize ")
        assert [tr for tier in t.trackers for tr in tier] == trackers
