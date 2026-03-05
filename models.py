"""
Data models for the Integration Health Monitor.
No I/O, no threading beyond Lock — pure domain layer.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional


class Status(Enum):
    UP   = "UP"
    WARN = "WARN"
    DOWN = "DOWN"


class Protocol(Enum):
    EDI_SFTP  = "EDI/SFTP"
    REST_JSON = "REST/JSON"
    SOAP_XML  = "SOAP/XML"


@dataclass
class Event:
    timestamp:    datetime
    carrier_name: str
    pro_number:   str
    event_type:   str
    location:     str
    latency_ms:   int
    is_error:     bool = False


@dataclass
class Integration:
    name:                 str
    protocol:             Protocol
    latency_range:        tuple
    event_interval_range: tuple     # (0, 0) = sentinel → always DOWN (Harbor Lines)
    error_rate_pct:       float

    # ── mutable state ─────────────────────────────────────────────────────────
    status:     Status             = field(default=Status.UP,  init=False)
    last_event: Optional[datetime] = field(default=None,       init=False)

    # ── internal (excluded from repr/init) ────────────────────────────────────
    _lock:               threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False)
    _created_at:         datetime       = field(
        default_factory=datetime.utcnow, init=False, repr=False)
    _event_timestamps:   deque          = field(
        default_factory=lambda: deque(maxlen=500), init=False, repr=False)
    _latency_samples:    deque          = field(
        default_factory=lambda: deque(maxlen=100), init=False, repr=False)
    _error_count_window: deque          = field(
        default_factory=lambda: deque(maxlen=500), init=False, repr=False)

    # ── write path ────────────────────────────────────────────────────────────

    def record_event(self, event: Event) -> None:
        """Called by the simulator thread after generating an event."""
        with self._lock:
            self._event_timestamps.append(event.timestamp)
            self._error_count_window.append(event.is_error)
            self._latency_samples.append(event.latency_ms)
            if not event.is_error:
                self.last_event = event.timestamp

    # ── read path (metrics) ───────────────────────────────────────────────────

    def avg_latency_ms(self) -> float:
        with self._lock:
            samples = list(self._latency_samples)
        return sum(samples) / len(samples) if samples else 0.0

    def events_per_minute(self) -> float:
        cutoff = datetime.utcnow() - timedelta(seconds=60)
        with self._lock:
            count = sum(1 for ts in self._event_timestamps if ts >= cutoff)
        return float(count)

    def recent_error_rate_pct(self) -> float:
        cutoff = datetime.utcnow() - timedelta(seconds=60)
        with self._lock:
            pairs = list(zip(self._event_timestamps, self._error_count_window))
        recent = [err for ts, err in pairs if ts >= cutoff]
        return (sum(recent) / len(recent)) * 100.0 if recent else 0.0

    # ── status recomputation (called by health-monitor thread) ────────────────

    def refresh_status(self) -> None:
        """Recompute and write self.status. Called every 5 s by Simulator."""
        now = datetime.utcnow()

        # Sentinel: Harbor Lines is always DOWN
        if self.event_interval_range == (0, 0):
            with self._lock:
                self.status = Status.DOWN
            return

        with self._lock:
            last = self.last_event

        # Grace period: don't penalise for missing the very first event at startup
        age = (now - self._created_at).total_seconds()
        if last is None:
            if age > 20:
                with self._lock:
                    self.status = Status.DOWN
            return  # still in warmup — keep current status

        # Stale: had events but went silent
        if (now - last).total_seconds() > 120:
            with self._lock:
                self.status = Status.DOWN
            return

        # WARN thresholds
        avg_lat  = self.avg_latency_ms()
        err_rate = self.recent_error_rate_pct()
        if avg_lat > 500 or err_rate > 5.0:
            with self._lock:
                self.status = Status.WARN
        else:
            with self._lock:
                self.status = Status.UP
