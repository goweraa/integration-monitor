# Integration Health Monitor

> **The problem:** A supply chain visibility platform like project44 maintains live connections to dozens or hundreds of carrier integrations simultaneously. When one goes silent — or starts throwing errors — someone needs to know immediately. This tool simulates what that monitoring looks like.

Built to demonstrate carrier integration operations skills relevant to a Technical Integration Manager role: tracking connection health, spotting degraded integrations before they fail, and understanding what "healthy" looks like across different protocols.

---

## What it does

A live terminal dashboard that monitors 5 carrier integrations in real time:

```
┌─────────────────────────────────────────────────────────────────────────┐
│              CARRIER INTEGRATION HEALTH MONITOR                         │
│                    Last updated: 14:32:07                               │
├──────────────────┬──────────┬──────────┬───────────┬────────┬──────────┤
│ Carrier          │ Protocol │ Status   │ Latency   │ Errors │ Last Seen│
├──────────────────┼──────────┼──────────┼───────────┼────────┼──────────┤
│ ACME Freight     │ EDI/SFTP │ ✓ UP     │   142ms   │  0.2%  │  just now│
│ FastShip LTL     │ REST/JSON│ ✓ UP     │    89ms   │  0.1%  │  just now│
│ Global Express   │ REST/JSON│ ⚠ WARN   │  1,847ms  │  8.3%  │     12s  │
│ Harbor Lines     │ SOAP/XML │ ✗ DOWN   │     —     │    —   │    4m 2s │
│ PrimeRoute TMS   │ REST/JSON│ ✓ UP     │   203ms   │  0.4%  │  just now│
└──────────────────┴──────────┴──────────┴───────────┴────────┴──────────┘
  [q] quit   [p] pause
```

Each carrier has a realistic failure profile:
- **ACME Freight** — healthy EDI/SFTP feed
- **FastShip LTL** — healthy REST API
- **Global Express** — degraded: high latency (1.8s) and rising error rate (8%+)
- **Harbor Lines** — down: no events received in over 4 minutes (silent carrier)
- **PrimeRoute TMS** — healthy REST API

---

## Why this matters in supply chain

When a carrier integration goes down, shippers lose visibility into their freight. They don't know if a shipment is on time, delayed, or delivered. In a platform managing thousands of shipments, a silent carrier is a critical issue.

A Technical Integration Manager needs to:
- Know which integrations are healthy at a glance
- Distinguish between "silent" (no data) and "erroring" (bad data)
- Catch degraded connections (high latency, rising errors) before they fail completely
- Know how long a carrier has been unreachable

This dashboard simulates exactly that operational reality — across EDI, REST, and SOAP integrations running in parallel.

---

## Installation

```bash
git clone https://github.com/goweraa/integration-monitor.git
cd integration-monitor
pip install rich
```

---

## Usage

```bash
python3 monitor.py
```

**Controls:**
- `q` — quit
- `p` — pause / resume

---

## Project structure

```
integration-monitor/
├── monitor.py      # Dashboard UI and main loop
├── simulator.py    # Simulates carrier data feeds with realistic failure modes
└── models.py       # Integration state and health models
```
