"""A small Prometheus-text metrics registry (ADR 0032).

``Counter`` and ``Histogram`` live in the process that serves ``/metrics`` (the
single-process API). Worker-side outcomes (job steps, model calls) are counted
in Redis by ``SharedCounters`` so the API can expose them too. Labels carry
only fixed vocabularies — route templates, methods, status classes, agent keys,
backends, step names — never tenant ids, user ids, or content. The shared keys
are therefore platform-scope, not a tenant cache (hard rule 7; ADR 0032).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

log = logging.getLogger("radbrain.metrics")
Labels = tuple[str, ...]
DEFAULT_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 300.0)
SHARED_PREFIX = "platform:metrics:"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _label_text(names: Sequence[str], values: Sequence[str], extra: str = "") -> str:
    parts = [f'{n}="{_escape(v)}"' for n, v in zip(names, values, strict=True)]
    if extra:
        parts.append(extra)
    return "{" + ",".join(parts) + "}" if parts else ""


class Counter:
    def __init__(self, name: str, help_text: str, labelnames: Sequence[str]) -> None:
        self.name, self.help, self.labelnames = name, help_text, tuple(labelnames)
        self._values: dict[Labels, float] = {}
        self._lock = threading.Lock()

    def inc(self, *labels: str, amount: float = 1.0) -> None:
        key = tuple(str(v) for v in labels)
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + amount

    def value(self, *labels: str) -> float:
        return self._values.get(tuple(labels), 0.0)

    def render(self) -> Iterable[str]:
        yield f"# HELP {self.name} {self.help}"
        yield f"# TYPE {self.name} counter"
        with self._lock:
            items = sorted(self._values.items())
        for labels, value in items:
            yield f"{self.name}{_label_text(self.labelnames, labels)} {value:g}"


class Histogram:
    def __init__(self, name: str, help_text: str, labelnames: Sequence[str],
                 buckets: Sequence[float] = DEFAULT_BUCKETS) -> None:
        self.name, self.help, self.labelnames = name, help_text, tuple(labelnames)
        self.buckets = tuple(sorted(buckets))
        self._data: dict[Labels, list[float]] = {}  # bucket counts..., sum, count
        self._lock = threading.Lock()

    def observe(self, value: float, *labels: str) -> None:
        key = tuple(str(v) for v in labels)
        with self._lock:
            row = self._data.setdefault(key, [0.0] * (len(self.buckets) + 2))
            for i, bound in enumerate(self.buckets):
                if value <= bound:
                    row[i] += 1
            row[-2] += value
            row[-1] += 1

    def count(self, *labels: str) -> float:
        row = self._data.get(tuple(labels))
        return row[-1] if row else 0.0

    def render(self) -> Iterable[str]:
        yield f"# HELP {self.name} {self.help}"
        yield f"# TYPE {self.name} histogram"
        with self._lock:
            items = sorted((k, list(v)) for k, v in self._data.items())
        for labels, row in items:
            for bound, hits in zip(self.buckets, row, strict=False):
                le = _label_text(self.labelnames, labels, f'le="{bound:g}"')
                yield f"{self.name}_bucket{le} {hits:g}"
            inf = _label_text(self.labelnames, labels, 'le="+Inf"')
            yield f"{self.name}_bucket{inf} {row[-1]:g}"
            yield f"{self.name}_sum{_label_text(self.labelnames, labels)} {row[-2]:g}"
            yield f"{self.name}_count{_label_text(self.labelnames, labels)} {row[-1]:g}"


class SharedCounters:
    """Counters kept in Redis hashes so every process adds to one total.

    Fail-open: when Redis is unreachable the increment is dropped, logged once,
    and not retried for ``cooldown_s`` so a dead Redis never slows a request.
    """

    def __init__(self, client_factory: Any, cooldown_s: float = 60.0) -> None:
        self._factory = client_factory
        self._client: Any = None
        self._down_until = 0.0
        self._warned = False
        self._cooldown = cooldown_s

    def _redis(self) -> Any | None:
        if time.monotonic() < self._down_until:
            return None
        if self._client is None:
            self._client = self._factory()
        return self._client

    def _failed(self, exc: Exception) -> None:
        self._down_until = time.monotonic() + self._cooldown
        if not self._warned:
            log.warning("shared_metrics_unavailable error=%s", type(exc).__name__)
            self._warned = True

    def inc(self, metric: str, labels: Mapping[str, str], amount: float = 1.0) -> None:
        field = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        try:
            client = self._redis()
            if client is not None:
                client.hincrbyfloat(SHARED_PREFIX + metric, field, amount)
        except Exception as exc:  # fail-open by design
            self._failed(exc)

    def read(self, metric: str) -> dict[str, float]:
        try:
            client = self._redis()
            if client is None:
                return {}
            raw = client.hgetall(SHARED_PREFIX + metric) or {}
        except Exception as exc:
            self._failed(exc)
            return {}
        return {_text(k): float(_text(v)) for k, v in raw.items()}


def _text(value: Any) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


def render_shared(metric: str, help_text: str, values: Mapping[str, float]) -> list[str]:
    lines = [f"# HELP {metric} {help_text}", f"# TYPE {metric} counter"]
    for field, value in sorted(values.items()):
        pairs = [p.split("=", 1) for p in field.split(",") if "=" in p]
        labels = "{" + ",".join(f'{k}="{_escape(v)}"' for k, v in pairs) + "}" if pairs else ""
        lines.append(f"{metric}{labels} {value:g}")
    return lines


def redis_factory(url: str) -> Any:
    def build() -> Any:
        import redis

        return redis.Redis.from_url(url, socket_connect_timeout=0.5, socket_timeout=0.5)

    return build


_shared: SharedCounters | None = None


def shared() -> SharedCounters:
    """The process-wide shared counters (Redis from ``REDIS_URL``)."""
    global _shared
    if _shared is None:
        _shared = SharedCounters(redis_factory(os.environ.get("REDIS_URL",
                                                              "redis://localhost:6379/0")))
    return _shared


def set_shared(counters: SharedCounters | None) -> None:
    """Replace the shared counters (tests use an in-memory fake)."""
    global _shared
    _shared = counters
