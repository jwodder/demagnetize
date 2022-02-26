from abc import ABC, abstractmethod
from ipaddress import AddressValueError, IPv4Address, IPv6Address
import struct
from typing import List
from ..peers import Peer
from ..util import InfoHash


class Tracker(ABC):
    @abstractmethod
    async def get_peers(self, info_hash: InfoHash) -> List[Peer]:
        ...


def unpack_peers(data: bytes) -> List[Peer]:
    peers: List[Peer] = []
    try:
        for (ipnum, port) in struct.iter_unpack("!IH", data):
            ip = str(IPv4Address(ipnum))
            peers.append(Peer(host=ip, port=port))
    except (struct.error, AddressValueError):
        raise ValueError("invalid 'peers' list")
    return peers


def unpack_peers6(data: bytes) -> List[Peer]:
    peers6: List[Peer] = []
    try:
        for (*ipbytes, port) in struct.iter_unpack("!16cH", data):
            ip = str(IPv6Address(b"".join(ipbytes)))
            peers6.append(Peer(host=ip, port=port))
    except (struct.error, AddressValueError):
        raise ValueError("invalid 'peers' list")
    return peers6
