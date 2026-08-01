"""Read-only AC and battery status from Linux power-supply sysfs."""

from __future__ import annotations

from pathlib import Path

from usb_cctv_recorder.application.dto import PowerProtectionState, PowerSource, PowerStatus


class LinuxPowerStatusAdapter:
    """Reports the current source; 5% is the documented Phase 6 critical-stop threshold."""

    CRITICAL_BATTERY_PERCENT = 5

    def __init__(self, power_supply_root: Path = Path("/sys/class/power_supply")) -> None:
        self._root = power_supply_root

    def status(self) -> PowerStatus:
        try:
            entries = tuple(path for path in self._root.iterdir() if path.is_dir())
        except OSError:
            return PowerStatus(PowerProtectionState.INACTIVE, PowerSource.UNKNOWN)
        ac_online = any(
            self._read(entry, "type") in {"Mains", "USB"} and self._read(entry, "online") == "1"
            for entry in entries
        )
        percentages = [
            int(value)
            for entry in entries
            if self._read(entry, "type") == "Battery"
            if (value := self._read(entry, "capacity")) is not None and value.isdigit()
        ]
        battery_percent = min(percentages) if percentages else None
        if ac_online:
            return PowerStatus(PowerProtectionState.INACTIVE, PowerSource.AC, battery_percent)
        if battery_percent is None:
            return PowerStatus(PowerProtectionState.INACTIVE, PowerSource.UNKNOWN)
        source = (
            PowerSource.CRITICAL_BATTERY
            if battery_percent <= self.CRITICAL_BATTERY_PERCENT
            else PowerSource.BATTERY
        )
        return PowerStatus(PowerProtectionState.INACTIVE, source, battery_percent)

    @staticmethod
    def _read(directory: Path, name: str) -> str | None:
        try:
            return (directory / name).read_text(encoding="utf-8").strip()
        except OSError:
            return None
