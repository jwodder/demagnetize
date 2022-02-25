from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from ipaddress import AddressValueError, IPv4Address, IPv6Address
import struct
from typing import List, cast
from flatbencode import decode
from httpx import AsyncClient, HTTPError
from .errors import TrackerError
from .peers import Peer
from .util import TRACE, InfoHash, log


class Tracker(ABC):
    @abstractmethod
    async def get_peers(self, info_hash: InfoHash) -> List[Peer]:
        ...


@dataclass
class HTTPTracker(Tracker):
    url: str
    peer_id: str
    peer_port: int

    async def get_peers(self, info_hash: InfoHash) -> List[Peer]:
        log.info("Requesting peers for %s from tracker at %s", info_hash, self.url)
        try:
            async with AsyncClient(follow_redirects=True) as client:
                r = await client.get(
                    self.url,
                    params={
                        "info_hash": bytes(info_hash),
                        "peer_id": self.peer_id,
                        "port": self.peer_port,
                        "uploaded": 0,
                        "downloaded": 0,
                        "left": 65535,  ### TODO: Look into
                        "event": "started",
                        "compact": 1,
                    },
                )
                if r.is_error:
                    raise TrackerError(
                        f"Request to tracker {self.url} returned {r.status_code}"
                    )
                ### TODO: Should we send a "stopped" event to the tracker now?
        except HTTPError as e:
            raise TrackerError(
                f"Error communicating with tracker {self.url}: {type(e).__name__}: {e}"
            )
        log.log(TRACE, "Tracker at %s replied with: %r", self.url, r.content)
        try:
            response = self.parse_response(r.content)
        except ValueError as e:
            raise TrackerError(f"Bad response from tracker at {self.url}: {e}")
        peers = cast(
            List[Peer], response.get(b"peers", []) + response.get(b"peers6", [])
        )
        log.info("Tracker at %s returned %d peers", self.url, len(peers))
        log.debug(  ### TODO: Make this message TRACE level?  Remove?
            "Tracker at %s returned peers: %s",
            self.url,
            ", ".join(map(str, peers)),
        )
        return peers

    @staticmethod
    def parse_response(content: bytes) -> dict:
        try:
            data = decode(content)
        except ValueError:
            raise ValueError("invalid bencoded data")
        if not isinstance(data, dict):
            raise ValueError("invalid response")
        if b"failure reason" in data:
            breason = data[b"failure reason"]
            if isinstance(breason, bytes):
                reason = breason.decode("utf-8", "replace")
            else:
                reason = "<UNDECODABLE>"
            raise ValueError(f"tracker query failed: {reason}")
        if b"peers" in data:
            peers: List[Peer] = []
            if isinstance(data[b"peers"], list):
                # Original format (BEP 0003)
                ### TODO
                raise NotImplementedError
            elif isinstance(data[b"peers"], bytes):
                # Compact format (BEP 0023)
                try:
                    for (ipnum, port) in struct.iter_unpack("!IH", data[b"peers"]):
                        ip = str(IPv4Address(ipnum))
                        peers.append(Peer(host=ip, port=port))
                except (struct.error, AddressValueError):
                    raise ValueError("invalid 'peers' list")
            else:
                raise ValueError("invalid 'peers' list")
            data[b"peers"] = peers
        if b"peers6" in data:
            peers6: List[Peer] = []
            if not isinstance(data[b"peers6"], bytes):
                raise ValueError("invalid 'peers6' list")
            # Compact format (BEP 0007)
            try:
                for (*ipnums, port) in struct.iter_unpack("!16cH", data[b"peers6"]):
                    ip = str(IPv6Address(b"".join(ipnums)))
                    peers6.append(Peer(host=ip, port=port))
            except (struct.error, AddressValueError):
                raise ValueError("invalid 'peers' list")
            data[b"peers6"] = peers6
        return data
