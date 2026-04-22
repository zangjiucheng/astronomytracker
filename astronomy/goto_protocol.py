from __future__ import annotations

import serial
from dataclasses import dataclass
from typing import Protocol

from astronomy.tracker_state import EphemerisSample, ra_to_hms, dec_to_dms


class GotoController(Protocol):
    def connect(self) -> None: ...
    def disconnect(self) -> None: ...
    def send_coordinates(self, sample: EphemerisSample) -> None: ...


@dataclass
class MeadeLX200Protocol:
    port: str = "/dev/ttyUSB0"
    baudrate: int = 9600
    timeout_sec: float = 3.0

    def __post_init__(self) -> None:
        self._serial: serial.Serial | None = None

    def connect(self) -> None:
        self._serial = serial.Serial(
            port=self.port,
            baudrate=self.baudrate,
            timeout=self.timeout_sec,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
        )

    def disconnect(self) -> None:
        if self._serial and self._serial.is_open:
            self._serial.close()

    def _send_command(self, cmd: str) -> str:
        if not self._serial or not self._serial.is_open:
            raise RuntimeError("Serial port not connected")
        self._serial.write(cmd.encode("ascii"))
        self._serial.flush()
        response = self._serial.read(64)
        return response.decode("ascii", errors="replace")

    def send_coordinates(self, sample: EphemerisSample) -> None:
        ra_hms = ra_to_hms(sample.ra_deg)
        dec_dms = dec_to_dms(sample.dec_deg)

        dec_sign = dec_dms[0]
        dec_parts = dec_dms[1:].split(":")
        dec_str = f"{dec_sign}{dec_parts[0]} {dec_parts[1]} {dec_parts[2]}"

        ra_parts = ra_hms.split(":")
        ra_str = f"{ra_parts[0]} {ra_parts[1]} {ra_parts[2]}"

        self._send_command(f":R{ra_str}#")
        self._send_command(f":D{dec_str}#")
        self._send_command(":MS#")

    def sync_to_target(self, sample: EphemerisSample) -> None:
        ra_hms = ra_to_hms(sample.ra_deg)
        dec_dms = dec_to_dms(sample.dec_deg)

        dec_sign = dec_dms[0]
        dec_parts = dec_dms[1:].split(":")
        dec_str = f"{dec_sign}{dec_parts[0]} {dec_parts[1]} {dec_parts[2]}"

        ra_parts = ra_hms.split(":")
        ra_str = f"{ra_parts[0]} {ra_parts[1]} {ra_parts[2]}"

        self._send_command(f":Rn{ra_str}#")
        self._send_command(f":Dn{dec_str}#")
