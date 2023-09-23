import platform
from typing import Any
import pytest
from demagnetize.bencode import bencode, partial_unbencode, unbencode
from demagnetize.errors import UnbencodeError


@pytest.mark.parametrize(
    "blob,data",
    [
        (b"4:spam", b"spam"),
        (b"i3e", 3),
        (b"l4:spam4:eggse", [b"spam", b"eggs"]),
        (b"d3:cow3:moo4:spam4:eggse", {b"cow": b"moo", b"spam": b"eggs"}),
        (b"d4:data4:\x00\x01\x02\x03e", {b"data": b"\x00\x01\x02\x03"}),
        (b"i0e", 0),
        (b"i-1e", -1),
        (b"i-10e", -10),
        (b"i35e", 35),
        (b"0:", b""),
        (b"le", []),
        (b"de", {}),
        (b"d8:msg_typei0e5:piecei0ee", {b"msg_type": 0, b"piece": 0}),
        (
            b"d1:md11:ut_metadatai3ee13:metadata_sizei31235ee",
            {b"m": {b"ut_metadata": 3}, b"metadata_size": 31235},
        ),
    ],
)
def test_bencode(blob: bytes, data: Any) -> None:
    assert unbencode(blob) == data
    assert bencode(data) == blob


@pytest.mark.parametrize(
    "blob",
    [
        b"i-0e",
        b"i00e",
        b"i04e",
        b"04:spam",
        b"-4:spam",
        b"-0:",
        b"24:short",
        b"4:longextra",
        b"l",
        b"q",
        b"d",
        b"di32e6:stringe",
        b"d6:bananai1e5:applei2e",
        b"i3.14e",
        b"i12-e",
        b"i 12e",
        b"i12 e",
        b"i12:",
        b"5eapple",
        pytest.param(
            b"l" * 1234 + b"e" * 1234,
            marks=pytest.mark.skipif(
                platform.python_implementation() == "PyPy",
                reason="Recursion depth is weird on PyPy",
            ),
        ),
    ],
)
def test_unbencode_error(blob: bytes) -> None:
    with pytest.raises(UnbencodeError):
        unbencode(blob)


@pytest.mark.parametrize(
    "blob,data,trailing",
    [
        (
            b"d8:msg_typei1e5:piecei0e10:total_sizei3425eeabcdefg",
            {b"msg_type": 1, b"piece": 0, b"total_size": 3425},
            b"abcdefg",
        ),
    ],
)
def test_partial_unbencode(blob: bytes, data: Any, trailing: bytes) -> None:
    assert partial_unbencode(blob) == (data, trailing)
