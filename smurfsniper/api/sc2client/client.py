"""Client for the StarCraft II local game API (``http://localhost:6119``).

No cache, no rate limit and a single try with a short timeout: the poller calls it
every 1.5 s. A refused connection raises ``Unavailable`` (SC2 is not running).
"""

from __future__ import annotations

import httpx
from pydantic import ValidationError

from smurfsniper.api.errors import BadResponse
from smurfsniper.api.sc2client.models import GameInfo, UiInfo
from smurfsniper.api.transport import HttpTransport, RetryPolicy

DEFAULT_URL = "http://localhost:6119"
SERVICE = "sc2"


def normalize_base_url(url: str | None) -> str:
    """Accept the old ``.../game`` endpoint form for back-compat."""
    url = (url or DEFAULT_URL).strip().rstrip("/")
    if url.endswith("/game"):
        url = url[: -len("/game")]
    return url or DEFAULT_URL


class LocalSc2Client:
    def __init__(self, base_url: str = DEFAULT_URL, *, transport: HttpTransport | None = None):
        self.base_url = normalize_base_url(base_url)
        self.transport = transport or HttpTransport(
            service=SERVICE,
            base_url=self.base_url,
            cache=None,
            limiter=None,
            retry=RetryPolicy(attempts=1),
            timeout=httpx.Timeout(1.5, connect=0.5),
            log_requests=False,
        )

    def game(self) -> GameInfo:
        data = self.transport.get_json("/game")
        try:
            return GameInfo.model_validate(data or {})
        except ValidationError as e:
            raise BadResponse(SERVICE, f"/game: {e.error_count()} validation error(s)") from e

    def ui(self) -> UiInfo:
        data = self.transport.get_json("/ui")
        try:
            return UiInfo.model_validate(data or {})
        except ValidationError as e:
            raise BadResponse(SERVICE, f"/ui: {e.error_count()} validation error(s)") from e

    def close(self) -> None:
        self.transport.close()
