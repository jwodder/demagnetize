from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional, cast
from urllib.parse import quote
from flatbencode import decode
from httpx import AsyncClient, HTTPError
from yarl import URL
from .base import Tracker, unpack_peers, unpack_peers6
from ..consts import CLIENT, LEFT, NUMWANT
from ..errors import TrackerError
from ..peers import Peer
from ..util import TRACE, InfoHash, log


@dataclass
class HTTPTracker(Tracker):
    url: URL
    peer_id: bytes
    peer_port: int

    def __str__(self) -> str:
        return f"<Tracker {self.url}>"

    async def get_peers(self, info_hash: InfoHash) -> List[Peer]:
        log.info("Requesting peers for %s from %s", info_hash, self)
        # As of v0.22.0, the only way to send a bytes query parameter through
        # httpx is if we do all of the encoding ourselves.
        params = (
            f"info_hash={quote(bytes(info_hash))}"
            f"&peer_id={quote(self.peer_id)}"
            f"&port={self.peer_port}"
            "&uploaded=0"
            "&downloaded=0"
            f"&left={LEFT}"
            "&event=started"
            "&compact=1"
            f"&numwant={NUMWANT}"
        )
        url = self.url.with_fragment(None)
        if url.query_string:
            target = f"{url}&{params}"
        else:
            target = f"{url}?{params}"
        try:
            async with AsyncClient(
                follow_redirects=True, headers={"User-Agent": CLIENT}
            ) as client:
                r = await client.get(target)
                if r.is_error:
                    raise TrackerError(f"Request to {self} returned {r.status_code}")
                ### TODO: Should we send a "stopped" event to the tracker now?
        except (HTTPError, OSError) as e:
            raise TrackerError(
                f"Error communicating with {self}: {type(e).__name__}: {e}"
            )
        log.log(TRACE, "%s replied with: %r", self, r.content)
        try:
            response = self.parse_response(r.content)
        except ValueError as e:
            raise TrackerError(f"Bad response from {self}: {e}")
        peers = cast(
            List[Peer], response.get(b"peers", []) + response.get(b"peers6", [])
        )
        log.info("%s returned %d peers", self, len(peers))
        log.log(TRACE, "%s returned peers: %s", self, ", ".join(map(str, peers)))
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
                    peer_id: Optional[bytes]
                    if b"peer id" in p and isinstance(p[b"peer id"], bytes):
                        peer_id = p[b"peer id"]
                    else:
                        peer_id = None
                    peers.append(Peer(host=ip, port=port, id=peer_id))
            elif isinstance(data[b"peers"], bytes):
                # Compact format (BEP 0023)
                peers = unpack_peers(data[b"peers"])
            else:
                raise ValueError("invalid 'peers' list")
            data[b"peers"] = peers
        if b"peers6" in data:
            if not isinstance(data[b"peers6"], bytes):
                raise ValueError("invalid 'peers6' list")
            # Compact format (BEP 0007)
            data[b"peers6"] = unpack_peers6(data[b"peers6"])
        return data
