"""
Simulation engine for the Integration Health Monitor.
Runs background threads per carrier and a health-monitor thread.
No rich imports — pure data production.
"""

from __future__ import annotations

import random
import threading
import time
from collections import deque
from datetime import datetime

from models import Event, Integration, Protocol


EVENT_TYPES = [
    "Pickup", "In Transit", "Arrival Scan", "Departure Scan",
    "Out for Delivery", "Delivered", "Exception",
    "Customs Cleared", "Held at Facility",
]

LOCATIONS = [
    "Chicago, IL", "Dallas, TX", "Los Angeles, CA", "Atlanta, GA",
    "Memphis, TN",  "Columbus, OH", "Louisville, KY", "Seattle, WA",
    "Newark, NJ",  "Houston, TX",  "Phoenix, AZ",    "Denver, CO",
]

_CARRIER_PROFILES: list[dict] = [
    dict(name="ACME Freight",   protocol=Protocol.EDI_SFTP,  latency_range=(50,  150),  event_interval_range=(2,  5),  error_rate_pct=0.0),
    dict(name="FastShip LTL",   protocol=Protocol.REST_JSON, latency_range=(80,  140),  event_interval_range=(1,  3),  error_rate_pct=0.0),
    dict(name="Global Express", protocol=Protocol.REST_JSON, latency_range=(700, 1400), event_interval_range=(8,  15), error_rate_pct=8.0),
    dict(name="Harbor Lines",   protocol=Protocol.SOAP_XML,  latency_range=(0,   0),    event_interval_range=(0,  0),  error_rate_pct=0.0),
    dict(name="PrimeRoute TMS", protocol=Protocol.REST_JSON, latency_range=(30,  90),   event_interval_range=(3,  6),  error_rate_pct=0.0),
]


def _build_integrations() -> list[Integration]:
    return [
        Integration(
            name=p["name"],
            protocol=p["protocol"],
            latency_range=p["latency_range"],
            event_interval_range=p["event_interval_range"],
            error_rate_pct=p["error_rate_pct"],
        )
        for p in _CARRIER_PROFILES
    ]


class Simulator:
    def __init__(self) -> None:
        self.integrations: list[Integration] = _build_integrations()
        self.event_log: deque[Event] = deque(maxlen=200)
        self._log_lock    = threading.Lock()
        self._stop_event  = threading.Event()
        self._pause_event = threading.Event()
        self._threads: list[threading.Thread] = []

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        for intg in self.integrations:
            if intg.event_interval_range == (0, 0):
                continue  # Harbor Lines — no carrier thread
            t = threading.Thread(
                target=self._carrier_loop,
                args=(intg,),
                daemon=True,
                name=f"carrier-{intg.name}",
            )
            self._threads.append(t)
            t.start()

        monitor = threading.Thread(
            target=self._health_monitor_loop,
            daemon=True,
            name="health-monitor",
        )
        self._threads.append(monitor)
        monitor.start()

    def stop(self) -> None:
        self._stop_event.set()
        for t in self._threads:
            t.join(timeout=2.0)

    # ── controls ──────────────────────────────────────────────────────────────

    def toggle_pause(self) -> None:
        if self._pause_event.is_set():
            self._pause_event.clear()
        else:
            self._pause_event.set()

    @property
    def paused(self) -> bool:
        return self._pause_event.is_set()

    # ── read ──────────────────────────────────────────────────────────────────

    def get_recent_events(self, n: int = 15) -> list[Event]:
        with self._log_lock:
            return list(self.event_log)[-n:]

    # ── background threads ────────────────────────────────────────────────────

    def _carrier_loop(self, intg: Integration) -> None:
        # Stagger startup so all carriers don't fire simultaneously
        self._stop_event.wait(timeout=random.uniform(0.2, 2.0))

        while not self._stop_event.is_set():
            if self._pause_event.is_set():
                self._stop_event.wait(timeout=0.5)
                continue

            interval = random.uniform(*intg.event_interval_range)
            # Interruptible sleep: returns True immediately if stop is signalled
            if self._stop_event.wait(timeout=interval):
                break
            if self._pause_event.is_set():
                continue

            latency  = random.randint(*intg.latency_range)
            is_error = random.random() < (intg.error_rate_pct / 100.0)

            event = Event(
                timestamp=datetime.utcnow(),
                carrier_name=intg.name,
                pro_number=f"PRO-{random.randint(100_000, 999_999)}",
                event_type=random.choice(EVENT_TYPES),
                location=random.choice(LOCATIONS),
                latency_ms=latency,
                is_error=is_error,
            )

            intg.record_event(event)
            if not is_error:
                with self._log_lock:
                    self.event_log.append(event)

    def _health_monitor_loop(self) -> None:
        while not self._stop_event.is_set():
            for intg in self.integrations:
                intg.refresh_status()
            self._stop_event.wait(timeout=5.0)
