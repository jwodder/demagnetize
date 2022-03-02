import pytest
from demagnetize.peer.extensions import BEP9MsgType, Extension, extbit
from demagnetize.peer.messages import (
    BEP9Message,
    Extended,
    Handshake,
    HaveAll,
    HaveNone,
    Message,
    Port,
)
from demagnetize.util import InfoHash


@pytest.mark.parametrize(
    "blob,handshake",
    [
        (
            b"\x13BitTorrent protocol\x00\x00\x00\x00\x00\x10\x00\x05k\xcb\xd4A"
            b"\xd7\xa0\x88\xc6;\xa8\xf8\x82\xe3\x12\x91\xd3\x85\xa7\x96L-TR3000"
            b"-vfu1svh0ewb6",
            Handshake(
                extensions={Extension.BEP10_EXTENSIONS, Extension.FAST, Extension.DHT},
                info_hash=InfoHash.from_bytes(
                    b"k\xcb\xd4A\xd7\xa0\x88\xc6;\xa8\xf8\x82\xe3\x12\x91\xd3"
                    b"\x85\xa7\x96L"
                ),
                peer_id=b"-TR3000-vfu1svh0ewb6",
            ),
        ),
        (
            b"\x13BitTorrent protocol\x00\x00\x00\x00\x00\x18\x00\x05k\xcb\xd4A"
            b"\xd7\xa0\x88\xc6;\xa8\xf8\x82\xe3\x12\x91\xd3\x85\xa7\x96L-qB4360"
            b"-5Ngjy9uIMl~O",
            Handshake(
                extensions={
                    Extension.BEP10_EXTENSIONS,
                    Extension.FAST,
                    Extension.DHT,
                    extbit(5, 0x08),
                },
                info_hash=InfoHash.from_bytes(
                    b"k\xcb\xd4A\xd7\xa0\x88\xc6;\xa8\xf8\x82\xe3\x12\x91\xd3"
                    b"\x85\xa7\x96L"
                ),
                peer_id=b"-qB4360-5Ngjy9uIMl~O",
            ),
        ),
    ],
)
def test_handshake(blob: bytes, handshake: Handshake) -> None:
    assert Handshake.parse(blob) == handshake
    assert bytes(handshake) == blob


@pytest.mark.parametrize(
    "blob,msg",
    [
        (b"\x00\x00\x00\x01\x0e", HaveAll()),
        (b"\x00\x00\x00\x01\x0f", HaveNone()),
        (b"\x00\x00\x00\x03\t\x88\xb7", Port(34999)),
        (b"\x00\x00\x00\x03\t\xea\xa5", Port(60069)),
        # Extended handshake:
        (
            b"\x00\x00\x00\xd5\x14\x00d12:complete_agoi1441e1:md11:lt_donthavei"
            b"7e10:share_modei8e11:upload_onlyi3e12:ut_holepunchi4e11:ut_metada"
            b"tai2e6:ut_pexi1ee13:metadata_sizei5436e4:reqqi500e11:upload_onlyi"
            b"1e1:v17:qBittorrent/4.3.66:yourip4:\x99\xa2D\x9be",
            Extended(
                msg_id=0,
                payload=(
                    b"d12:complete_agoi1441e1:md11:lt_donthavei7e10:share_modei"
                    b"8e11:upload_onlyi3e12:ut_holepunchi4e11:ut_metadatai2e6:u"
                    b"t_pexi1ee13:metadata_sizei5436e4:reqqi500e11:upload_onlyi"
                    b"1e1:v17:qBittorrent/4.3.66:yourip4:\x99\xa2D\x9be"
                ),
            ),
        ),
        # ut_pex:
        (
            b"\x00\x00\x00'\x14\x01d5:added12:V`\\\xe5\xc8\xd5\xb2\x9b\x8b\xa8"
            b"\x88\xb77:added.f2:\x10\x10e",
            Extended(
                msg_id=1,
                payload=(
                    b"d5:added12:V`\\\xe5\xc8\xd5\xb2\x9b\x8b\xa8\x88\xb77:adde"
                    b"d.f2:\x10\x10e"
                ),
            ),
        ),
        (
            b"\x00\x00\x00.\x14\x01d5:added18:V`\\\xe5\xc8\xd5\xb2\x9b\x8b\xa8"
            b"\x88\xb7\xb9\x15\xd8\x95\t\x847:added.f3:\x10\x12\x10e",
            Extended(
                msg_id=1,
                payload=(
                    b"d5:added18:V`\\\xe5\xc8\xd5\xb2\x9b\x8b\xa8\x88\xb7\xb9"
                    b"\x15\xd8\x95\t\x847:added.f3:\x10\x12\x10e"
                ),
            ),
        ),
        # ut_metadata:
        (
            b"\x00\x00\x00X\x14\x03d8:msg_typei1e5:piecei0e10:total_sizei5436ee"
            b"d5:filesld6:lengthi267661684e4:pathl72:...",
            Extended(
                msg_id=3,
                payload=(
                    b"d8:msg_typei1e5:piecei0e10:total_sizei5436eed5:filesld6:l"
                    b"engthi267661684e4:pathl72:..."
                ),
            ),
        ),
        (
            b"\x00\x00\x00\x1b\x14\x03d8:msg_typei0e5:piecei0ee",
            Extended(msg_id=3, payload=b"d8:msg_typei0e5:piecei0ee"),
        ),
    ],
)
def test_message(blob: bytes, msg: Message) -> None:
    assert Message.parse(blob) == msg
    assert bytes(msg) == blob


@pytest.mark.parametrize(
    "ext,b9msg,msg_id",
    [
        (
            Extended(msg_id=3, payload=b"d8:msg_typei0e5:piecei0ee"),
            BEP9Message(msg_type=BEP9MsgType.REQUEST, piece=0),
            3,
        ),
        (
            Extended(
                msg_id=3,
                payload=(
                    b"d8:msg_typei1e5:piecei0e10:total_sizei5436eed5:filesld6:l"
                    b"engthi267661684e4:pathl72:..."
                ),
            ),
            BEP9Message(
                msg_type=BEP9MsgType.DATA,
                piece=0,
                total_size=5436,
                payload=b"d5:filesld6:lengthi267661684e4:pathl72:...",
            ),
            3,
        ),
    ],
)
def test_bep9_message(ext: Extended, b9msg: BEP9Message, msg_id: int) -> None:
    assert BEP9Message.parse(ext.payload) == b9msg
    assert b9msg.compose(msg_id) == ext
