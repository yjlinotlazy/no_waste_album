"""Best-effort request telemetry for Home Command Center app stats."""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


_WRITE_LOCK = threading.Lock()


def route_for_target(target: str) -> str:
    return urlsplit(target).path or "/"


class CountingWriter:
    def __init__(self, wrapped: Any) -> None:
        self._wrapped = wrapped
        self.bytes_written = 0

    def write(self, data: bytes) -> int:
        self.bytes_written += len(data)
        return self._wrapped.write(data)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._wrapped, name)


class RequestLogger:
    def __init__(self, root: Path, app_id: str = "no_waste_album") -> None:
        self.path = root / "server_logs" / app_id / "raw"

    def record(self, *, target: str, method: str, status: int, request_size: int, response_size: int, started_at: float) -> None:
        event = {
            "timestamp": datetime.fromtimestamp(started_at).astimezone().isoformat(),
            "method": method,
            "route": route_for_target(target),
            "status": int(status),
            "request_bytes": int(request_size),
            "response_bytes": int(response_size),
            "latency_ms": round(max(0.0, (time.time() - started_at) * 1000), 3),
        }
        try:
            self.path.mkdir(parents=True, exist_ok=True)
            destination = self.path / f"{datetime.fromtimestamp(started_at).date().isoformat()}.jsonl"
            line = json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
            with _WRITE_LOCK:
                with destination.open("a", encoding="utf-8") as stream:
                    stream.write(line)
        except Exception:
            pass
