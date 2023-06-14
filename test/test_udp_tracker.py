from demagnetize.peer import Peer
from demagnetize.trackers.base import AnnounceEvent
from demagnetize.trackers.udp import (
    UDPAnnounceResponse,
    build_announce_request,
    build_connection_request,
    parse_announce_response,
    parse_connection_response,
)
from demagnetize.util import InfoHash, Key


def test_build_connection_request() -> None:
    assert (
        build_connection_request(0x5C310D73)
        == b"\x00\x00\x04\x17'\x10\x19\x80\x00\x00\x00\x00\\1\rs"
    )


def test_parse_connection_response() -> None:
    assert (
        parse_connection_response(
            0x5C310D73, b"\x00\x00\x00\x00\\1\rs\\\xcb\xdf\xdb\x15|%\xba"
        )
        == 0x5CCBDFDB157C25BA
    )


def test_build_announce_request() -> None:
    assert build_announce_request(
        transaction_id=-1523061017,
        connection_id=0x5CCBDFDB157C25BA,
        info_hash=InfoHash.from_string("4c3e215f9e50b06d708a74c9b0e66e08bce520aa"),
        peer_id=b"-TR3000-12nig788rk3b",
        peer_port=60069,
        key=Key(0x2C545EDE),
        event=AnnounceEvent.STARTED,
        downloaded=0,
        uploaded=0,
        left=(1 << 63) - 1,
        numwant=80,
        urldata="",
    ) == (
        b"\\\xcb\xdf\xdb\x15|%\xba\x00\x00\x00\x01\xa57\xee\xe7L>!_\x9eP"
        b"\xb0mp\x8at\xc9\xb0\xe6n\x08\xbc\xe5 \xaa-TR3000-12nig788rk3b\x00"
        b"\x00\x00\x00\x00\x00\x00\x00\x7f\xff\xff\xff\xff\xff\xff\xff\x00"
        b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00\x00\x00\x00,T^"
        b"\xde\x00\x00\x00P\xea\xa5"
    )


def test_build_announce_request_with_urldata() -> None:
    assert build_announce_request(
        transaction_id=-1523061017,
        connection_id=0x5CCBDFDB157C25BA,
        info_hash=InfoHash.from_string("4c3e215f9e50b06d708a74c9b0e66e08bce520aa"),
        peer_id=b"-TR3000-12nig788rk3b",
        peer_port=60069,
        key=Key(0x2C545EDE),
        event=AnnounceEvent.STARTED,
        downloaded=0,
        uploaded=0,
        left=(1 << 63) - 1,
        numwant=80,
        urldata="/announce",
    ) == (
        b"\\\xcb\xdf\xdb\x15|%\xba\x00\x00\x00\x01\xa57\xee\xe7L>!_\x9eP"
        b"\xb0mp\x8at\xc9\xb0\xe6n\x08\xbc\xe5 \xaa-TR3000-12nig788rk3b\x00"
        b"\x00\x00\x00\x00\x00\x00\x00\x7f\xff\xff\xff\xff\xff\xff\xff\x00"
        b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00\x00\x00\x00,T^"
        b"\xde\x00\x00\x00P\xea\xa5\x02\x09/announce"
    )


def test_parse_announce_response() -> None:
    assert parse_announce_response(
        transaction_id=-1523061017,
        is_ipv6=False,
        resp=(
            b"\x00\x00\x00\x01\xa57\xee\xe7\x00\x00\x07\x08\x00\x00\x00\x03\x00"
            b"\x00\x00\x1a\x17Qr\xeb\xc9,\xbfe\xfe\xe0`\x07\xb9\x15\xd8\x95\t"
            b"\x84\x9a\x15rd\x8f\xfe\xd5\x98\xbb\xebH\xda\xb2\x9b\x8b\xa8\x88"
            b"\xb7\xc3N6\xd3\x7f\xa4\xacbGNV\xe1\xb0\x7f\xe6\xc6)\xaa\xd4f%\xba"
            b"\xca\x7f\xa0\xb2\xbc\xcb\x1a\xe1\xb9\x15\xd8\x86\x80\x163\x0fh"
            b"\xca8L]#\x92\xd4CB.\xf6\x03\xcd\xe3\xaa\xb9\x15\xd9M\xe1\x06V`\\"
            b"\xe5\xc8\xd5Q\x06'\x9b\xc8\xd5\xb9A\x87\xb1\xe7\xb7N\x89\x17\x16M"
            b"\xfc\xc1\x13\xce/\x1a\xe1\xb9&\x0e\xbf\xc64_\xf5l\xfd\xe1w\xb9"
            b"\x99\xb3<\xf20\x99\xa2D\x9b\xea\xa5W\xf9\x86\x13\xd8\xb2\x9a\r"
            b"\x01\x87\xc8\xd5\xb9\x9f\x9e9\x82\x1a\x8a\xc77%\x97S"
        ),
    ) == UDPAnnounceResponse(
        interval=1800,
        leechers=3,
        seeders=26,
        peers=[
            Peer("23.81.114.235", 51500),
            Peer("191.101.254.224", 24583),
            Peer("185.21.216.149", 2436),
            Peer("154.21.114.100", 36862),
            Peer("213.152.187.235", 18650),
            Peer("178.155.139.168", 34999),
            Peer("195.78.54.211", 32676),
            Peer("172.98.71.78", 22241),
            Peer("176.127.230.198", 10666),
            Peer("212.102.37.186", 51839),
            Peer("160.178.188.203", 6881),
            Peer("185.21.216.134", 32790),
            Peer("51.15.104.202", 14412),
            Peer("93.35.146.212", 17218),
            Peer("46.246.3.205", 58282),
            Peer("185.21.217.77", 57606),
            Peer("86.96.92.229", 51413),
            Peer("81.6.39.155", 51413),
            Peer("185.65.135.177", 59319),
            Peer("78.137.23.22", 19964),
            Peer("193.19.206.47", 6881),
            Peer("185.38.14.191", 50740),
            Peer("95.245.108.253", 57719),
            Peer("185.153.179.60", 62000),
            Peer("153.162.68.155", 60069),
            Peer("87.249.134.19", 55474),
            Peer("154.13.1.135", 51413),
            Peer("185.159.158.57", 33306),
            Peer("138.199.55.37", 38739),
        ],
    )


def test_parse_announce_response_no_peers() -> None:
    assert parse_announce_response(
        transaction_id=-904575366,
        is_ipv6=False,
        resp=(
            b"\x00\x00\x00\x01\xca\x15Fz\x00\x00\x07\x08\x00\x00\x00\x02"
            b"\x00\x00\x00\x1a"
        ),
    ) == UDPAnnounceResponse(interval=1800, leechers=2, seeders=26, peers=[])
