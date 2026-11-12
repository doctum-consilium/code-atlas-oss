"""Thermal guard: a hot laptop takes a break instead of crashing.

Before each heavy batch (embeddings, reranker, local chat model), the GPU temperature
(``nvidia-smi``) and the CPU package temperature (``/sys/class/thermal``) are read. Above the
limit, work waits until it drops below ``limit - 8 °C`` (hysteresis: no flapping around the
limit). An unreadable sensor never blocks anything.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

HYSTERESIS = 8.0


def read_gpu() -> float | None:
    """Temperature of the hottest NVIDIA GPU, in °C."""
    try:
        output = subprocess.run(
            ["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    values = [float(v) for v in output.split() if v.strip().replace(".", "", 1).isdigit()]
    return max(values) if values else None


def read_cpu(root: Path = Path("/sys/class/thermal")) -> float | None:
    """CPU package temperature (zone ``x86_pkg_temp``, else the hottest zone), in °C."""
    zones: dict[str, float] = {}
    for zone in root.glob("thermal_zone*"):
        try:
            zones[(zone / "type").read_text().strip()] = int((zone / "temp").read_text()) / 1000
        except (OSError, ValueError):
            continue
    if not zones:
        return None
    return zones.get("x86_pkg_temp", max(zones.values()))


@dataclass
class Guard:
    """Pauses while the GPU or the CPU is above its limit."""

    enabled: bool = True
    gpu_max_c: float = 80.0
    cpu_max_c: float = 88.0
    gpu: Callable[[], float | None] = read_gpu
    cpu: Callable[[], float | None] = read_cpu
    sleep: Callable[[float], None] = time.sleep
    notify: Callable[[str], None] = print
    pauses: int = 0

    def _too_hot(self, margin: float) -> str | None:
        g, c = self.gpu(), self.cpu()
        if g is not None and g >= self.gpu_max_c - margin:
            return f"GPU at {g:.0f} °C"
        if c is not None and c >= self.cpu_max_c - margin:
            return f"CPU at {c:.0f} °C"
        return None

    def wait(self, pause_s: float = 15.0, max_s: float = 1800.0) -> None:
        """Return at once if everything is cool; otherwise wait for it to cool down."""
        if not self.enabled:
            return
        reason = self._too_hot(0.0)
        if reason is None:
            return
        self.pauses += 1
        self.notify(f"Thermal pause: {reason}, waiting for it to cool down…")
        waited = 0.0
        while self._too_hot(HYSTERESIS) is not None and waited < max_s:
            self.sleep(pause_s)
            waited += pause_s
        self.notify(f"Resuming after {waited:.0f} s.")


GUARD = Guard()


def configure(enabled: bool, gpu_max_c: float, cpu_max_c: float) -> None:
    """Apply the ``[thermal]`` settings to the shared guard."""
    GUARD.enabled, GUARD.gpu_max_c, GUARD.cpu_max_c = enabled, gpu_max_c, cpu_max_c
