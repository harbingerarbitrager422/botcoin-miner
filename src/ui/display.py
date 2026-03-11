"""Minimal TUI for mining status using rich."""

from __future__ import annotations

import logging
import time
from collections import deque
from datetime import datetime

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

logger = logging.getLogger(__name__)

MAX_LOG_LINES = 12


class MinerDisplay:
    def __init__(self):
        self.console = Console()
        self._live: Live | None = None

        # Header state
        self.wallet: str = ""
        self.epoch_id: int | None = None
        self.epoch_remaining: int = 0
        self.model: str = ""
        self.credits: str = "?"
        self.staked: str = ""

        # Stats
        self.total_solves: int = 0
        self.total_attempts: int = 0
        self.session_start: float = time.monotonic()
        self.status: str = "Starting..."

        # Log buffer
        self._log_lines: deque[str] = deque(maxlen=MAX_LOG_LINES)

    def start(self) -> None:
        self._live = Live(
            self._render(),
            console=self.console,
            refresh_per_second=1,
        )
        self._live.start()

    def stop(self) -> None:
        if self._live:
            self._live.stop()
            self._live = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()

    def _refresh(self) -> None:
        if self._live:
            self._live.update(self._render())

    def _render(self) -> Panel:
        # Header section
        header = Table.grid(padding=(0, 2))
        header.add_column(ratio=1)
        header.add_column(ratio=1)

        wallet_short = self.wallet[:6] + "..." + self.wallet[-4:] if len(self.wallet) > 12 else self.wallet
        epoch_str = str(self.epoch_id) if self.epoch_id is not None else "?"
        header.add_row(
            f"Wallet: {wallet_short}",
            f"Epoch: {epoch_str}",
        )
        header.add_row(
            f"Model:  {self.model}",
            f"Credits: {self.credits}",
        )
        if self.staked:
            header.add_row(f"Staked: {self.staked}", "")

        # Stats section
        elapsed = int(time.monotonic() - self.session_start)
        hours, remainder = divmod(elapsed, 3600)
        minutes = remainder // 60
        time_str = f"{hours}h {minutes}m" if hours else f"{minutes}m"

        pass_rate = (
            f"{self.total_solves / self.total_attempts * 100:.0f}%"
            if self.total_attempts > 0
            else "N/A"
        )

        stats = Text()
        stats.append(f"Solves: {self.total_solves}")
        stats.append(f" | Pass rate: {pass_rate}")
        stats.append(f" | Session: {time_str}")
        stats.append(f"\nStatus: {self.status}")

        # Log section
        log_text = Text()
        for line in self._log_lines:
            log_text.append(line + "\n")

        # Combine
        combined = Table.grid()
        combined.add_column()
        combined.add_row(header)
        combined.add_row(Text("─" * 50, style="dim"))
        combined.add_row(stats)
        combined.add_row(Text("─" * 50, style="dim"))
        combined.add_row(log_text)

        return Panel(combined, title="BOTCOIN Miner", border_style="blue")

    def update_status(self, msg: str) -> None:
        self.status = msg
        self._refresh()

    def update_epoch(self, epoch_id: int, remaining: int = 0) -> None:
        self.epoch_id = epoch_id
        self.epoch_remaining = remaining
        self._refresh()

    def update_credits(self, balance: str) -> None:
        self.credits = balance
        self._refresh()

    def update_solve_stats(self, total: int, passed: int) -> None:
        self.total_attempts = total
        self.total_solves = passed
        self._refresh()

    def log(self, msg: str, level: str = "info") -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        prefix = {
            "info": "",
            "warning": "[!] ",
            "error": "[ERR] ",
            "success": "[OK] ",
        }.get(level, "")
        line = f"[{ts}] {prefix}{msg}"
        self._log_lines.append(line)
        # Also log to file-based logger
        log_fn = getattr(logger, level if level != "success" else "info")
        log_fn(msg)
        self._refresh()
