from __future__ import annotations
from typing import TYPE_CHECKING, Any, List, Optional, Type, TypeVar, cast
from urllib.parse import quote
import attr
from flatbencode import decode
from httpx import AsyncClient, HTTPError
from .base import Tracker, TrackerSession, unpack_peers, unpack_peers6
from ..consts import CLIENT, LEFT, NUMWANT
from ..errors import TrackerError
from ..peer import Peer
from ..util import TRACE, InfoHash, log

if TYPE_CHECKING:
    from ..core import Demagnetizer

T = TypeVar("T")


class HTTPTracker(Tracker):
    async def connect(self, app: Demagnetizer) -> HTTPTrackerSession:
        return HTTPTrackerSession(
            tracker=self,
            app=app,
            client=AsyncClient(follow_redirects=True, headers={"User-Agent": CLIENT}),
        )


@attr.define
class HTTPTrackerSession(TrackerSession):
    tracker: HTTPTracker
    app: Demagnetizer
    client: AsyncClient

    async def aclose(self) -> None:
        await self.client.aclose()

    async def announce(self, info_hash: InfoHash) -> List[Peer]:
        log.info("Requesting peers for %s from %s", info_hash, self.tracker)
        # As of v0.22.0, the only way to send a bytes query parameter through
        # httpx is if we do all of the encoding ourselves.
        params = (
            f"info_hash={quote(bytes(info_hash))}"
            f"&peer_id={quote(self.app.peer_id)}"
            f"&port={self.app.peer_port}"
            "&uploaded=0"
            "&downloaded=0"
            f"&left={LEFT}"
            "&event=started"
            "&compact=1"
            f"&numwant={NUMWANT}"
            f"&key={quote(str(self.app.key))}"
        )
        url = self.tracker.url.with_fragment(None)
        if url.query_string:
            target = f"{url}&{params}"
        else:
            target = f"{url}?{params}"
        try:
            r = await self.client.get(target)
        except (HTTPError, OSError) as e:
            raise TrackerError(
                f"Error communicating with {self.tracker}: {type(e).__name__}: {e}"
            )
        if r.is_error:
            raise TrackerError(f"Request to {self.tracker} returned {r.status_code}")
        ### TODO: Should we send a "stopped" event to the tracker now?
        log.log(TRACE, "%s replied with: %r", self.tracker, r.content)
        try:
            response = Response.parse(r.content)
        except ValueError as e:
            raise TrackerError(f"Bad response from {self.tracker}: {e}")
        if response.failure_reason is not None:
            raise TrackerError(
                f"Request to {self.tracker} failed: {response.failure_reason}"
            )
        if response.warning_message is not None:
            log.info(
                "%s replied with warning: %s", self.tracker, response.warning_message
            )
        log.info("%s returned %d peers", self.tracker, len(response.peers))
        log.log(
            TRACE,
            "%s returned peers: %s",
            self.tracker,
            ", ".join(map(str, response.peers)),
        )
        return response.peers


@attr.define
class Response:
    failure_reason: Optional[str] = None
    warning_message: Optional[str] = None
    interval: Optional[int] = None
    min_interval: Optional[int] = None
    tracker_id: Optional[bytes] = None
    complete: Optional[int] = None
    incomplete: Optional[int] = None
    peers: List[Peer] = attr.Factory(list)

    @classmethod
    def parse(cls, content: bytes) -> Response:
        # Unknown fields and (most) fields of the wrong type are discarded
        try:
            data = decode(content)
        except ValueError:
            raise ValueError("invalid bencoded data")
        if not isinstance(data, dict):
            raise ValueError("invalid response")
        r = cls()
        if (failure := data.get(b"failure reason")) is not None:
            if isinstance(failure, bytes):
                r.failure_reason = failure.decode("utf-8", "replace")
            else:
                # Do our best to salvage the situation
                r.failure_reason = str(failure)
        if (warning := get_typed_value(data, b"warning message", bytes)) is not None:
            r.warning_message = warning.decode("utf-8", "replace")
        r.interval = get_typed_value(data, b"interval", int)
        r.min_interval = get_typed_value(data, b"min interval", int)
        r.tracker_id = get_typed_value(data, b"tracker id", bytes)
        r.complete = get_typed_value(data, b"complete", int)
        r.incomplete = get_typed_value(data, b"incomplete", int)
        if b"peers" in data:
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
                    r.peers.append(Peer(host=ip, port=port, id=peer_id))
            elif isinstance(data[b"peers"], bytes):
                # Compact format (BEP 0023)
                r.peers.extend(unpack_peers(data[b"peers"]))
            else:
                raise ValueError("invalid 'peers' list")
        if b"peers6" in data:
            if not isinstance(data[b"peers6"], bytes):
                raise ValueError("invalid 'peers6' list")
            # Compact format (BEP 0007)
            r.peers.extend(unpack_peers6(data[b"peers6"]))
        return r


def get_typed_value(data: dict, key: Any, klass: Type[T]) -> Optional[T]:
    value = data.get(key)
    if isinstance(value, klass):
        return value
    else:
        return None
