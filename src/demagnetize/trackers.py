from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List
from httpx import AsyncClient, HTTPError
from .error import TrackerError
from .peers import Peer
from .util import InfoHash, log


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
            async with AsyncClient() as client:
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
                if not r.ok:
                    raise TrackerError(
                        f"Request to tracker {self.url} returned {r.status_code}"
                    )
                ### TODO: Should we send a "stopped" event to the tracker now?
            response = HTTPTrackerResponse.parse(r.content)
            ### TODO: Emit an INFO message with the number of peers?
            log.debug(
                "Tracker at %s returned peers: %s",
                self.url,
                ", ".join(map(str, response.peers)),
            )
            return response.peers
        except HTTPError as e:
            raise TrackerError(
                f"Error communicating with tracker {self.url}: {type(e).__name__}: {e}"
            )


@dataclass
class HTTPTrackerResponse:
    interval: int
    peers: List[Peer]

    @classmethod
    def parse(cls, content: bytes) -> HTTPTrackerResponse:
        ### Parse
        ### Raise TrackerError if "failure reason" present
        ###   (Insert the tracker URL into the error at some spot)
        raise NotImplementedError
