# Integration Health Monitor

A live terminal dashboard that simulates real-time monitoring of carrier API integrations — the kind of tool a Technical Integration Manager uses to watch over multiple carrier connections at once.

Built as a portfolio project demonstrating supply chain integration operations skills relevant to platforms like project44.

---

## Features

- Live-updating terminal dashboard (no browser required)
- Monitors 5 simulated carrier integrations simultaneously
- Tracks: status (UP/WARN/DOWN), latency, error rate, event count, last seen timestamp
- Realistic failure scenarios: high latency, elevated error rates, silent carriers
- Color-coded status indicators for at-a-glance triage

---

## Simulated Integrations

| Carrier | Protocol | Profile |
|---------|----------|---------|
| ACME Freight | EDI / SFTP | Healthy |
| FastShip LTL | REST / JSON | Healthy |
| Global Express | REST / JSON | WARN — high latency + errors |
| Harbor Lines | SOAP / XML | DOWN — no events received |
| PrimeRoute TMS | REST / JSON | Healthy |

---

## Installation

```bash
git clone https://github.com/yourusername/integration-monitor.git
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

## Why This Matters

When you're managing dozens of carrier integrations, you need a way to know instantly which ones are healthy and which need attention. A DOWN carrier means shipment visibility gaps for customers. A WARN state (high latency, rising error rate) is an early warning before things break. This tool simulates exactly that operational reality.
