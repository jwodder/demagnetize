from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from ipaddress import AddressValueError, IPv4Address, IPv6Address
import struct
from typing import List, Optional, cast
from urllib.parse import quote
from flatbencode import decode
from httpx import AsyncClient, HTTPError
from yarl import URL
from .errors import TrackerError
from .peers import Peer
from .util import TRACE, InfoHash, log


class Tracker(ABC):
    @abstractmethod
    async def get_peers(self, info_hash: InfoHash) -> List[Peer]:
        ...


@dataclass
class HTTPTracker(Tracker):
    url: URL
    peer_id: str
    peer_port: int

    async def get_peers(self, info_hash: InfoHash) -> List[Peer]:
        log.info("Requesting peers for %s from tracker at %s", info_hash, self.url)
        # As of v0.22.0, the only way to send a bytes query parameter through
        # httpx is if we do all of the encoding ourselves.
        params = (
            f"info_hash={quote(bytes(info_hash))}"
            f"&peer_id={quote(self.peer_id)}"
            f"&port={self.peer_port}"
            "&uploaded=0"
            "&downloaded=0"
            "&left=65535"  ### TODO: Look into
            "&event=started"
            "&compact=1"
        )
        url = self.url.with_fragment(None)
        if url.query_string:
            target = f"{url}&{params}"
        else:
            target = f"{url}?{params}"
        try:
            async with AsyncClient(follow_redirects=True) as client:
                r = await client.get(target)
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
        log.log(
            TRACE,
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
                for p in data[b"peers"]:
                    if not isinstance(p, dict):
                        raise ValueError("invalid 'peers' list")
                    try:
                        ip = cast(bytes, p[b"ip"]).decode("utf-8")
                    except Exception:
                        raise ValueError("invalid 'peers' list")
                    if b"port" in p and isinstance(p[b"port"], int):
                        port = p[b"port"]
                    else:
                        raise ValueError("invalid 'peers' list")
                    peer_id: Optional[str]
                    if b"peer id" in p and isinstance(p[b"peer id"], bytes):
                        try:
                            peer_id = p[b"peer id"].decode("utf-8")
                        except UnicodeDecodeError:
                            raise ValueError("invalid 'peers' list")
                    else:
                        peer_id = None
                    peers.append(Peer(host=ip, port=port, id=peer_id))
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


@dataclass
class UDPTracker(Tracker):
    host: str
    port: int
    peer_id: str
    peer_port: int

    async def get_peers(self, info_hash: InfoHash) -> List[Peer]:
        raise NotImplementedError
