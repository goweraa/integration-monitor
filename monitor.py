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
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from models import Status
from simulator import Simulator


# ── Status display strings ────────────────────────────────────────────────────

_STATUS_LABEL: dict[Status, str] = {
    Status.UP:   "[bold green]● UP[/bold green]",
    Status.WARN: "[bold yellow]● WARN[/bold yellow]",
    Status.DOWN: "[bold red]● DOWN[/bold red]",
}

_ALERT_PREFIX: dict[Status, str] = {
    Status.DOWN: "[bold red]▲ DOWN[/bold red]",
    Status.WARN: "[bold yellow]⚠ WARN[/bold yellow]",
}


# ── Section builders ──────────────────────────────────────────────────────────

def _build_header(paused: bool) -> Panel:
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d  %H:%M:%S UTC")
    pause_note = "  [bold yellow]⏸ PAUSED[/bold yellow]" if paused else ""
    left  = f"[bold cyan]Integration Health Monitor[/bold cyan]  [dim]project44 · Supply Chain Visibility[/dim]{pause_note}"
    right = f"[dim]{now}[/dim]"
    grid = Table.grid(expand=True)
    grid.add_column(justify="left")
    grid.add_column(justify="right")
    grid.add_row(left, right)
    return Panel(grid, border_style="cyan", height=3)


def _build_integrations_table(integrations: list) -> Panel:
    table = Table(
        box=box.SIMPLE_HEAD,
        expand=True,
        header_style="bold white",
        show_edge=False,
        pad_edge=True,
    )
    table.add_column("Carrier",     min_width=18, style="bold white")
    table.add_column("Protocol",    min_width=12, style="white")
    table.add_column("Status",      min_width=10, justify="center")
    table.add_column("Avg Latency", min_width=12, justify="right")
    table.add_column("Events/min",  min_width=11, justify="right")
    table.add_column("Error Rate",  min_width=11, justify="right")
    table.add_column("Last Event",  min_width=12)

    for intg in integrations:
        avg_lat  = intg.avg_latency_ms()
        epm      = intg.events_per_minute()
        err_rate = intg.recent_error_rate_pct()

        if avg_lat == 0:
            lat_str = "[dim white]—[/dim white]"
        elif avg_lat > 500:
            lat_str = f"[bold yellow]{avg_lat:.0f} ms[/bold yellow]"
        else:
            lat_str = f"[green]{avg_lat:.0f} ms[/green]"

        if err_rate > 10:
            err_str = f"[bold red]{err_rate:.1f}%[/bold red]"
        elif err_rate > 5:
            err_str = f"[yellow]{err_rate:.1f}%[/yellow]"
        else:
            err_str = f"[dim white]{err_rate:.1f}%[/dim white]"

        if intg.last_event is None:
            last_str = "[red]never[/red]"
        else:
            delta = (datetime.utcnow() - intg.last_event).total_seconds()
            last_str = (
                f"[white]{int(delta)}s ago[/white]"
                if delta < 60
                else f"[yellow]{int(delta // 60)}m {int(delta % 60)}s ago[/yellow]"
            )

        epm_str = f"[white]{epm:.1f}[/white]"

        table.add_row(
            intg.name,
            intg.protocol.value,
            _STATUS_LABEL[intg.status],
            lat_str,
            epm_str,
            err_str,
            last_str,
        )

    return Panel(table, title="[bold white]Carrier Integrations[/bold white]", border_style="cyan")


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
                f"  {_ALERT_PREFIX[Status.DOWN]}  [bold white]{intg.name}[/bold white]"
                f"  [white]{reason}[/white]"
            )

        elif intg.status == Status.WARN:
            reasons: list[str] = []
            if intg.avg_latency_ms() > 500:
                reasons.append(f"latency {intg.avg_latency_ms():.0f}ms (threshold 500ms)")
            if intg.recent_error_rate_pct() > 5.0:
                reasons.append(f"error rate {intg.recent_error_rate_pct():.1f}% (threshold 5%)")
            lines.append(
                f"  {_ALERT_PREFIX[Status.WARN]}  [bold white]{intg.name}[/bold white]"
                f"  [white]{', '.join(reasons)}[/white]"
            )

    has_down = any(i.status == Status.DOWN for i in integrations)
    has_warn = any(i.status == Status.WARN for i in integrations)
    border = "red" if has_down else ("yellow" if has_warn else "green")

    content = (
        "\n".join(lines)
        if lines
        else "[green]  ✓ All integrations healthy[/green]"
    )
    return Panel(content, title="[bold white]Active Alerts[/bold white]", border_style=border)


def _build_event_log_panel(events: list) -> Panel:
    table = Table(
        box=box.SIMPLE_HEAD,
        expand=True,
        show_header=True,
        header_style="bold white",
        show_edge=False,
        pad_edge=True,
    )
    table.add_column("Time",     width=10, no_wrap=True, style="white")
    table.add_column("Carrier",  width=14, no_wrap=True, style="white")
    table.add_column("PRO #",    width=12, no_wrap=True, style="green")
    table.add_column("Event",    width=22, no_wrap=True, style="bold white")
    table.add_column("Location", width=16, no_wrap=True, style="white")
    table.add_column("Latency",  width=8,  no_wrap=True, justify="right")

    for event in reversed(events):
        lat_color = "yellow" if event.latency_ms > 500 else "cyan"
        carrier_short = event.carrier_name.split()[0]
        table.add_row(
            event.timestamp.strftime("%H:%M:%S"),
            carrier_short,
            event.pro_number,
            event.event_type,
            event.location,
            f"[{lat_color}]{event.latency_ms}ms[/{lat_color}]",
        )

    return Panel(
        table,
        title="[bold white]Event Log[/bold white]  [dim white](live · newest first)[/dim white]",
        border_style="blue",
    )


def _build_footer() -> Panel:
    shortcuts = "[white]  [bold]q[/bold] Quit    [bold]p[/bold] Pause / Resume[/white]"
    return Panel(shortcuts, border_style="dim white", height=3)


def _build_display(sim: Simulator) -> Group:
    integrations = sim.integrations
    events       = sim.get_recent_events(10)
    return Group(
        _build_header(sim.paused),
        _build_integrations_table(integrations),
        _build_alerts_panel(integrations),
        _build_event_log_panel(events),
        _build_footer(),
    )


# ── Keyboard input ────────────────────────────────────────────────────────────

def _keyboard_thread(sim: Simulator, stop: threading.Event) -> None:
    try:
        import tty
        import termios
    except ImportError:
        return

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
    console  = Console()
    sim      = Simulator()
    sim.start()

    kbd_stop = threading.Event()
    kbd_thread = threading.Thread(
        target=_keyboard_thread,
        args=(sim, kbd_stop),
        daemon=True,
        name="keyboard",
    )
    kbd_thread.start()

    try:
        with Live(
            _build_display(sim),
            console=console,
            refresh_per_second=1,
            screen=False,
            vertical_overflow="visible",
        ) as live:
            while not kbd_stop.is_set():
                live.update(_build_display(sim))
                time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        kbd_stop.set()
        sim.stop()

    console.print("\n[bold green]Integration Health Monitor stopped.[/bold green]")


if __name__ == "__main__":
    main()
