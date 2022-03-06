from __future__ import annotations
from typing import Optional
import pytest
from demagnetize.peer.extensions import (
    BEP9MsgType,
    BEP10Extension,
    BEP10Registry,
    Extension,
    extbit,
)
from demagnetize.peer.messages import (
    BEP9Message,
    Extended,
    ExtendedHandshake,
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
    "payload,handshake,extensions,extension_names,client,metadata_size",
    [
        (
            b"d12:complete_agoi1441e1:md11:lt_donthavei7e10:share_modei8e11:upl"
            b"oad_onlyi3e12:ut_holepunchi4e11:ut_metadatai2e6:ut_pexi1ee13:meta"
            b"data_sizei5436e4:reqqi500e11:upload_onlyi1e1:v17:qBittorrent/4.3."
            b"66:yourip4:\x99\xa2D\x9be",
            ExtendedHandshake(
                {
                    b"complete_ago": 1441,
                    b"m": {
                        b"lt_donthave": 7,
                        b"share_mode": 8,
                        b"upload_only": 3,
                        b"ut_holepunch": 4,
                        b"ut_metadata": 2,
                        b"ut_pex": 1,
                    },
                    b"metadata_size": 5436,
                    b"reqq": 500,
                    b"upload_only": 1,
                    b"v": b"qBittorrent/4.3.6",
                    b"yourip": b"\x99\xa2D\x9b",
                }
            ),
            BEP10Registry.from_dict(
                {BEP10Extension.METADATA: 2, BEP10Extension.PEX: 1}
            ),
            [
                "lt_donthave",
                "share_mode",
                "upload_only",
                "ut_holepunch",
                "ut_metadata",
                "ut_pex",
            ],
            "qBittorrent/4.3.6",
            5436,
        ),
        (
            b"d1:ei0e4:ipv616:\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\x011:md11:ut_metad"
            b"atai3e6:ut_pexi1ee1:pi60069e4:reqqi512e11:upload_onlyi0e1:v17:Tra"
            b"nsmission 3.00e",
            ExtendedHandshake(
                {
                    b"e": 0,
                    b"ipv6": b"\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\x01",
                    b"m": {
                        b"ut_metadata": 3,
                        b"ut_pex": 1,
                    },
                    b"p": 60069,
                    b"reqq": 512,
                    b"upload_only": 0,
                    b"v": b"Transmission 3.00",
                }
            ),
            BEP10Registry.from_dict(
                {BEP10Extension.METADATA: 3, BEP10Extension.PEX: 1}
            ),
            ["ut_metadata", "ut_pex"],
            "Transmission 3.00",
            None,
        ),
    ],
)
def test_extended_handshake(
    payload: bytes,
    handshake: ExtendedHandshake,
    extensions: BEP10Registry,
    extension_names: list[str],
    client: Optional[str],
    metadata_size: Optional[int],
) -> None:
    assert ExtendedHandshake.from_extended_payload(payload) == handshake
    assert handshake.to_extended() == Extended(0, payload)
    assert handshake.extensions == extensions
    assert handshake.extension_names == extension_names
    assert handshake.client == client
    assert handshake.metadata_size == metadata_size


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
    extensions = BEP10Registry.from_dict({BEP10Extension.METADATA: msg_id})
    assert ext.decompose(extensions) == b9msg
    assert b9msg.to_extended(extensions) == ext
