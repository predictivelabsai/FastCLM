"""Low-cardinality HTTP metrics and privacy-safe structured request logs."""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections import Counter
from uuid import uuid4


LOGGER = logging.getLogger("fastclm.requests")
LOGGER.setLevel(logging.INFO)
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class HttpMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requests: Counter[tuple[str, int]] = Counter()
        self._duration_seconds: Counter[tuple[str, int]] = Counter()
        self._active = 0

    def start(self) -> None:
        with self._lock:
            self._active += 1

    def finish(self, method: str, status_code: int, duration_seconds: float) -> None:
        key = (method.upper(), status_code)
        with self._lock:
            self._active = max(0, self._active - 1)
            self._requests[key] += 1
            self._duration_seconds[key] += duration_seconds

    def render(self) -> str:
        with self._lock:
            requests = dict(self._requests)
            durations = dict(self._duration_seconds)
            active = self._active
        lines = [
            "# HELP fastclm_http_requests_total Completed HTTP requests.",
            "# TYPE fastclm_http_requests_total counter",
        ]
        for (method, status), value in sorted(requests.items()):
            lines.append(f'fastclm_http_requests_total{{method="{method}",status="{status}"}} {value}')
        lines.extend([
            "# HELP fastclm_http_request_duration_seconds_total Cumulative HTTP request duration.",
            "# TYPE fastclm_http_request_duration_seconds_total counter",
        ])
        for (method, status), value in sorted(durations.items()):
            lines.append(f'fastclm_http_request_duration_seconds_total{{method="{method}",status="{status}"}} {value:.9f}')
        lines.extend([
            "# HELP fastclm_http_requests_active Requests currently being processed.",
            "# TYPE fastclm_http_requests_active gauge",
            f"fastclm_http_requests_active {active}",
            "",
        ])
        return "\n".join(lines)


http_metrics = HttpMetrics()


class ObservabilityMiddleware:
    """ASGI middleware that does not buffer streaming assistant responses."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        raw_headers = dict(scope.get("headers", ()))
        supplied_request_id = raw_headers.get(b"x-request-id", b"").decode("ascii", "ignore")
        request_id = supplied_request_id if _REQUEST_ID.fullmatch(supplied_request_id) else uuid4().hex
        method = scope.get("method", "GET").upper()
        started = time.monotonic()
        status_code = 500
        http_metrics.start()

        async def observed_send(message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = list(message.get("headers", ()))
                if not any(name.lower() == b"x-request-id" for name, _value in headers):
                    headers.append((b"x-request-id", request_id.encode("ascii")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, observed_send)
        finally:
            duration = time.monotonic() - started
            http_metrics.finish(method, status_code, duration)
            route = scope.get("route")
            LOGGER.info(json.dumps({
                "event": "http.request",
                "request_id": request_id,
                "method": method,
                "route": getattr(route, "path", "unmatched"),
                "status": status_code,
                "duration_ms": round(duration * 1000, 3),
            }, separators=(",", ":"), sort_keys=True))
