import pytest
from demagnetize.peer import Peer
from demagnetize.trackers.http import HTTPAnnounceResponse


@pytest.mark.parametrize(
    "blob,obj",
    [
        (
            b"d8:completei47e10:incompletei5e8:intervali1800e12:min intervali18"
            b"00e5:peers300:w\x94bls\xdf\xd8\xb4C,\x1a\xe1\xba\x16\xdf\xe8\x0f0"
            b"\xc1(\r\xab\xc8\xd5\xb32\xe9\xec\x86~\xd4UX]A\xf1-\x0e\xc30\xd6"
            b"\xa1g\xd9\xe8z\xcbv\xbfe\xaen\xdc\xb41%/G\xa1\xa7N\xc5i\x88A\xf1B"
            b"s\x93\xd1\x00\x01\x9a\x1d\x83\xb6\xc8\xd5\xbc\xd18-N\\-[\x17\x85"
            b"\xc8\xd5\xb9U\x96>ZIH\x15\x11\x05\xebT\xc2%`S\x83\xb0\\V\x90\x04S"
            b"Y\xb3\xec\xac\x06\xaa[Wns\x08.\xc9\xc8o\xe0\xf5\x94\xe8R\xaa\xe86"
            b"\x1a\xe1\x1b!nb\xc4\x85Mn\x83*\xa15\x17\x13\x8dp\xb3\xe9\xc1(\r"
            b"\xa2\xb3\x8c\xc3\xf6xC-\x15\xb9\x95Z\t\xc7I-\x0c\xdct\xc8\xd5E"
            b"\xaaM\xe3\x10\x9f\xd5\xf5\xb3;z\xed\xd9\x8a\xd5\x1d\xa1\x0b\xd4f9"
            b"K!\x9b\xb9\x99\xb3\x1b\xe6'gW\xd6\xdeu\xcfeXO\xc1\xc8-\xd4:x<."
            b"\xa6\x18%a\x1a\xc8\xd5\xc1 \x7f\x98\xc8\xd5\xd9\x8a\xc2^\xe0\x02m"
            b"\xc9\x98\xa6\x00\x01\xb9\xba\xf9\t\x1a\xe1\x86\x13\xbc[\xce\x9bD"
            b'\xeb,G\xd9|.5\xfd\xf1\xd4\xf1\x1b"\x14I\xa4\xbe\xb0)\x1b\xedp'
            b"\xcb\xac\xf1\xe0.I\x84m\xc9\x98\xaf\x00\x01e",
            HTTPAnnounceResponse(
                complete=47,
                incomplete=5,
                interval=1800,
                min_interval=1800,
                peers=[
                    Peer("119.148.98.108", 29663),
                    Peer("216.180.67.44", 6881),
                    Peer("186.22.223.232", 3888),
                    Peer("193.40.13.171", 51413),
                    Peer("179.50.233.236", 34430),
                    Peer("212.85.88.93", 16881),
                    Peer("45.14.195.48", 54945),
                    Peer("103.217.232.122", 52086),
                    Peer("191.101.174.110", 56500),
                    Peer("49.37.47.71", 41383),
                    Peer("78.197.105.136", 16881),
                    Peer("66.115.147.209", 1),
                    Peer("154.29.131.182", 51413),
                    Peer("188.209.56.45", 20060),
                    Peer("45.91.23.133", 51413),
                    Peer("185.85.150.62", 23113),
                    Peer("72.21.17.5", 60244),
                    Peer("194.37.96.83", 33712),
                    Peer("92.86.144.4", 21337),
                    Peer("179.236.172.6", 43611),
                    Peer("87.110.115.8", 11977),
                    Peer("200.111.224.245", 38120),
                    Peer("82.170.232.54", 6881),
                    Peer("27.33.110.98", 50309),
                    Peer("77.110.131.42", 41269),
                    Peer("23.19.141.112", 46057),
                    Peer("193.40.13.162", 45964),
                    Peer("195.246.120.67", 11541),
                    Peer("185.149.90.9", 51017),
                    Peer("45.12.220.116", 51413),
                    Peer("69.170.77.227", 4255),
                    Peer("213.245.179.59", 31469),
                    Peer("217.138.213.29", 41227),
                    Peer("212.102.57.75", 8603),
                    Peer("185.153.179.27", 58919),
                    Peer("103.87.214.222", 30159),
                    Peer("101.88.79.193", 51245),
                    Peer("212.58.120.60", 11942),
                    Peer("24.37.97.26", 51413),
                    Peer("193.32.127.152", 51413),
                    Peer("217.138.194.94", 57346),
                    Peer("109.201.152.166", 1),
                    Peer("185.186.249.9", 6881),
                    Peer("134.19.188.91", 52891),
                    Peer("68.235.44.71", 55676),
                    Peer("46.53.253.241", 54513),
                    Peer("27.34.20.73", 42174),
                    Peer("176.41.27.237", 28875),
                    Peer("172.241.224.46", 18820),
                    Peer("109.201.152.175", 1),
                ],
            ),
        ),
        (
            b"d8:intervali1800e5:peers6:iiiipp6:peers618:iiiiiiiiiiiiiiiippe",
            HTTPAnnounceResponse(
                interval=1800,
                peers=[
                    Peer("105.105.105.105", 28784),
                    Peer("6969:6969:6969:6969:6969:6969:6969:6969", 28784),
                ],
            ),
        ),
    ],
)
def test_parse_response(blob: bytes, obj: HTTPAnnounceResponse) -> None:
    assert HTTPAnnounceResponse.parse(blob) == obj


@pytest.mark.parametrize(
    "blob",
    [
        b"d8:completei45e10:downloadedi8384e10:incompletei4e8:intervali900e12:min"
        b" intervali300e6:peers66:\x00\x00\x00\x00\x00\x0010:tracker id7:AniRenae",
    ],
)
def test_parse_bad_response(blob: bytes) -> None:
    with pytest.raises(ValueError):
        HTTPAnnounceResponse.parse(blob)
