from typing import List
import pytest
from demagnetize.peer.extensions import Extension


@pytest.mark.parametrize(
    "extensions,blob",
    [([Extension.BEP10_EXTENSIONS, Extension.FAST], b"\0\0\0\0\0\x10\0\x04")],
)
def test_extension_compile(extensions: List[Extension], blob: bytes) -> None:
    assert Extension.compile(extensions) == blob
