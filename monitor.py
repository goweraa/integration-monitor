"""
Integration Health Monitor — rich TUI entry point.
Displays live carrier integration health across a full-screen terminal dashboard.

Run:
    cd integration-monitor
    python3 monitor.py

Controls:
    q  — Quit
    p  — Pause / Resume simulation
"""

from __future__ import annotations

import sys
import time
import threading
from datetime import datetime, timezone

from rich import box
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from models import Status
from simulator import Simulator


# ── Status display strings ────────────────────────────────────────────────────

_STATUS_LABEL: dict[Status, str] = {
    Status.UP:   "[bold green]● UP[/bold green]",
    Status.WARN: "[bold yellow]● WARN[/bold yellow]",
    Status.DOWN: "[bold red]● DOWN[/bold red]",
}

_ALERT_PREFIX: dict[Status, str] = {
    Status.DOWN: "[red]▲ DOWN[/red]",
    Status.WARN: "[yellow]⚠ WARN[/yellow]",
}


# ── Panel builders ────────────────────────────────────────────────────────────

def _build_header() -> Panel:
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d  %H:%M:%S UTC")
    grid = Table.grid(expand=True)
    grid.add_column(justify="left")
    grid.add_column(justify="right")
    grid.add_row(
        "[bold cyan]Integration Health Monitor[/bold cyan]"
        "  [dim]project44 · Supply Chain Visibility[/dim]",
        f"[dim]{now}[/dim]",
    )
    return Panel(grid, style="on grey7", height=3)


def _build_integrations_table(integrations: list) -> Panel:
    table = Table(
        box=box.SIMPLE_HEAD,
        expand=True,
        header_style="bold dim white",
        show_edge=False,
        pad_edge=False,
    )
    table.add_column("Carrier",     min_width=16, style="bold")
    table.add_column("Protocol",    min_width=10)
    table.add_column("Status",      min_width=9,  justify="center")
    table.add_column("Avg Latency", min_width=11, justify="right")
    table.add_column("Events/min",  min_width=10, justify="right")
    table.add_column("Error Rate",  min_width=10, justify="right")
    table.add_column("Last Event",  min_width=12)

    for intg in integrations:
        avg_lat  = intg.avg_latency_ms()
        epm      = intg.events_per_minute()
        err_rate = intg.recent_error_rate_pct()

        # Latency — colour-code degraded values
        if avg_lat == 0:
            lat_str = "[dim]—[/dim]"
        elif avg_lat > 500:
            lat_str = f"[bold yellow]{avg_lat:.0f}ms[/bold yellow]"
        else:
            lat_str = f"[green]{avg_lat:.0f}ms[/green]"

        # Error rate
        if err_rate > 10:
            err_str = f"[bold red]{err_rate:.1f}%[/bold red]"
        elif err_rate > 5:
            err_str = f"[yellow]{err_rate:.1f}%[/yellow]"
        else:
            err_str = f"[dim]{err_rate:.1f}%[/dim]"

        # Time since last event
        if intg.last_event is None:
            last_str = "[red dim]never[/red dim]"
        else:
            delta = (datetime.utcnow() - intg.last_event).total_seconds()
            last_str = (
                f"[dim]{int(delta)}s ago[/dim]"
                if delta < 60
                else f"[dim]{int(delta // 60)}m ago[/dim]"
            )

        table.add_row(
            intg.name,
            intg.protocol.value,
            _STATUS_LABEL[intg.status],
            lat_str,
            f"[dim]{epm:.1f}[/dim]",
            err_str,
            last_str,
        )

    return Panel(
        table,
        title="[bold]Carrier Integrations[/bold]",
        border_style="cyan",
    )


def _build_alerts_panel(integrations: list) -> Panel:
    lines: list[str] = []

    for intg in integrations:
        if intg.status == Status.DOWN:
            if intg.event_interval_range == (0, 0):
                reason = "Carrier API unreachable — verify SOAP endpoint and credentials"
            elif intg.last_event is None:
                reason = "No events received — check connection and firewall rules"
            else:
                reason = "No events in >2 minutes — possible API outage"
            lines.append(
                f"{_ALERT_PREFIX[Status.DOWN]}  [bold]{intg.name}[/bold]"
                f" — [dim]{reason}[/dim]"
            )

        elif intg.status == Status.WARN:
            reasons: list[str] = []
            if intg.avg_latency_ms() > 500:
                reasons.append(f"latency {intg.avg_latency_ms():.0f}ms (threshold 500ms)")
            if intg.recent_error_rate_pct() > 5.0:
                reasons.append(f"error rate {intg.recent_error_rate_pct():.1f}% (threshold 5%)")
            lines.append(
                f"{_ALERT_PREFIX[Status.WARN]}  [bold]{intg.name}[/bold]"
                f" — [dim]{', '.join(reasons)}[/dim]"
            )

    has_down = any(i.status == Status.DOWN for i in integrations)
    has_warn = any(i.status == Status.WARN for i in integrations)
    border = "red" if has_down else ("yellow" if has_warn else "green")

    content = (
        "\n".join(lines)
        if lines
        else "[green dim]  All integrations healthy[/green dim]"
    )
    return Panel(content, title="[bold]Active Alerts[/bold]", border_style=border)


def _build_event_log_panel(events: list) -> Panel:
    table = Table(
        box=None,
        expand=True,
        show_header=True,
        header_style="bold dim",
        padding=(0, 1),
        show_edge=False,
    )
    table.add_column("Time",     width=8,  no_wrap=True, style="dim")
    table.add_column("Carrier",  width=11, no_wrap=True)
    table.add_column("PRO #",    width=10, no_wrap=True, style="green")
    table.add_column("Event",    width=18, no_wrap=True, style="bold")
    table.add_column("Location", width=14, no_wrap=True, style="dim")
    table.add_column("ms",       width=5,  no_wrap=True, justify="right")

    for event in reversed(events):
        lat_color   = "yellow" if event.latency_ms > 500 else "cyan"
        carrier_short = event.carrier_name.split()[0]  # "ACME", "FastShip", etc.
        table.add_row(
            event.timestamp.strftime("%H:%M:%S"),
            carrier_short,
            event.pro_number,
            event.event_type,
            event.location,
            f"[{lat_color}]{event.latency_ms}[/{lat_color}]",
        )

    return Panel(
        table,
        title="[bold]Event Log[/bold] [dim](live · newest first)[/dim]",
        border_style="blue",
    )


def _build_footer(paused: bool) -> Panel:
    pause_note = "  [bold yellow]⏸  PAUSED[/bold yellow]   " if paused else ""
    shortcuts  = "[dim][bold]q[/bold] Quit    [bold]p[/bold] Pause / Resume[/dim]"
    return Panel(f"{pause_note}{shortcuts}", style="on grey7", height=3)


# ── Layout wiring ─────────────────────────────────────────────────────────────

def _build_layout() -> Layout:
    layout = Layout(name="root")
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="body"),
        Layout(name="footer", size=3),
    )
    layout["body"].split_row(
        Layout(name="left",  ratio=3),  # ~60 %
        Layout(name="right", ratio=2),  # ~40 %
    )
    layout["left"].split_column(
        Layout(name="table"),
        Layout(name="alerts", size=8),  # fixed height for alerts
    )
    return layout


def _refresh_layout(layout: Layout, sim: Simulator) -> None:
    integrations = sim.integrations
    events       = sim.get_recent_events(15)

    layout["header"].update(_build_header())
    layout["table"].update(_build_integrations_table(integrations))
    layout["alerts"].update(_build_alerts_panel(integrations))
    layout["right"].update(_build_event_log_panel(events))
    layout["footer"].update(_build_footer(sim.paused))


# ── Keyboard input ────────────────────────────────────────────────────────────

def _keyboard_thread(sim: Simulator, stop: threading.Event) -> None:
    try:
        import tty
        import termios
    except ImportError:
        return  # Windows — keyboard handling not available

    fd  = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        while not stop.is_set():
            ch = sys.stdin.read(1)
            if ch.lower() == "q":
                stop.set()
                break
            elif ch.lower() == "p":
                sim.toggle_pause()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    console = Console()
    sim     = Simulator()
    sim.start()

    layout   = _build_layout()
    kbd_stop = threading.Event()

    kbd_thread = threading.Thread(
        target=_keyboard_thread,
        args=(sim, kbd_stop),
        daemon=True,
        name="keyboard",
    )
    kbd_thread.start()

    try:
        with Live(layout, console=console, refresh_per_second=1, screen=True):
            while not kbd_stop.is_set():
                _refresh_layout(layout, sim)
                time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        kbd_stop.set()
        sim.stop()

    console.print("\n[bold green]Integration Health Monitor stopped.[/bold green]")


if __name__ == "__main__":
    main()
