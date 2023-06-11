from __future__ import annotations
from typing import TYPE_CHECKING, ClassVar, Optional, TypeVar, cast
from urllib.parse import quote
import attr
from httpx import AsyncClient, HTTPError
from .base import (
    AnnounceEvent,
    AnnounceResponse,
    Tracker,
    TrackerSession,
    unpack_peers,
    unpack_peers6,
)
from ..bencode import unbencode
from ..consts import CLIENT, LEFT, NUMWANT
from ..errors import TrackerError, TrackerFailure, UnbencodeError
from ..peer import Peer
from ..util import TRACE, InfoHash, get_string, get_typed_value, log

if TYPE_CHECKING:
    from ..core import Demagnetizer

T = TypeVar("T")


class HTTPTracker(Tracker):
    SCHEMES: ClassVar[list[str]] = ["http", "https"]

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

    async def announce(
        self,
        info_hash: InfoHash,
        event: AnnounceEvent,
        downloaded: int = 0,
        uploaded: int = 0,
        left: int = LEFT,
    ) -> HTTPAnnounceResponse:
        # As of v0.22.0, the only way to send a bytes query parameter through
        # httpx is if we do all of the encoding ourselves.
        params = (
            f"info_hash={quote(bytes(info_hash))}"
            f"&peer_id={quote(self.app.peer_id)}"
            f"&port={self.app.peer_port}"
            f"&uploaded={uploaded}"
            f"&downloaded={downloaded}"
            f"&left={left}"
            f"&numwant={NUMWANT}"
            f"&key={quote(str(self.app.key))}"
            "&compact=1"
        )
        if event.http_value:
            params += f"&event={event.http_value}"
        url = self.tracker.url.with_fragment(None)
        if url.query_string:
            target = f"{url}&{params}"
        else:
            target = f"{url}?{params}"
        try:
            r = await self.client.get(target)
        except HTTPError as e:
            raise TrackerError(
                tracker=self.tracker,
                info_hash=info_hash,
                msg=f"{type(e).__name__}: {e}",
            )
        if r.is_error:
            raise TrackerError(
                tracker=self.tracker,
                info_hash=info_hash,
                msg=f"Request to tracker returned {r.status_code}",
            )
        try:
            response = HTTPAnnounceResponse.parse(r.content)
        except ValueError as e:
            log.log(TRACE, "Bad response from %s: %r", self.tracker, r.content)
            raise TrackerError(
                tracker=self.tracker, info_hash=info_hash, msg=f"Bad response: {e}"
            )
        if response.warning_message is not None:
            log.warning(
                "%s replied with warning: %s", self.tracker, response.warning_message
            )
        return response


@attr.define
class HTTPAnnounceResponse(AnnounceResponse):
    warning_message: Optional[str] = None
    min_interval: Optional[int] = None
    tracker_id: Optional[bytes] = None
    complete: Optional[int] = None
    incomplete: Optional[int] = None

    @classmethod
    def parse(cls, content: bytes) -> HTTPAnnounceResponse:
        # Unknown fields and (most) fields of the wrong type are discarded
        try:
            data = unbencode(content)
        except UnbencodeError as e:
            raise ValueError(f"invalid bencoded data: {e}")
        if not isinstance(data, dict):
            raise ValueError("invalid response")
        if (failure := data.get(b"failure reason")) is not None:
            if isinstance(failure, bytes):
                failure_reason = failure.decode("utf-8", "replace")
            else:
                # Do our best to salvage the situation
                failure_reason = str(failure)
            raise TrackerFailure(failure_reason)
        if (interval := get_typed_value(data, b"interval", int)) is None:
            # Just fill in a reasonable default
            interval = 1800
        peers: list[Peer] = []
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
                    peers.append(Peer(host=ip, port=port, id=peer_id))
            elif isinstance(data[b"peers"], bytes):
                # Compact format (BEP 0023)
                peers.extend(unpack_peers(data[b"peers"]))
            else:
                raise ValueError("invalid 'peers' list")
        if b"peers6" in data:
            if not isinstance(data[b"peers6"], bytes):
                raise ValueError("invalid 'peers6' list")
            # Compact format (BEP 0007)
            peers.extend(unpack_peers6(data[b"peers6"]))
        return cls(
            interval=interval,
            peers=peers,
            warning_message=get_string(data, b"warning message"),
            min_interval=get_typed_value(data, b"min interval", int),
            tracker_id=get_typed_value(data, b"tracker id", bytes),
            complete=get_typed_value(data, b"complete", int),
            incomplete=get_typed_value(data, b"incomplete", int),
        )
