from __future__ import annotations
from typing import TYPE_CHECKING
import attr

if TYPE_CHECKING:
    from .peer import Peer
    from .trackers import Tracker
    from .util import InfoHash


@attr.define
class TrackerError(Exception):
    tracker: Tracker
    info_hash: InfoHash
    msg: str

    def __str__(self) -> str:
        return f"Error announcing to {self.tracker} for {self.info_hash}: {self.msg}"


@attr.define
class PeerError(Exception):
    peer: Peer
    info_hash: InfoHash
    msg: str

    def __str__(self) -> str:
        return f"Error communicating with {self.peer} for {self.info_hash}: {self.msg}"


class DemagnetizeError(Exception):
    pass


class UnbencodeError(ValueError):
    pass


class TrackerFailure(Exception):
    # Raised when tracker returns a failure message
    ### TODO: Come up with a better name?
    pass
