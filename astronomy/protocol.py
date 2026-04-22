from __future__ import annotations

import math
import socket
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Protocol

import serial


class GotoController(Protocol):
    def connect(self) -> None: ...
    def disconnect(self) -> None: ...
    def send_coordinates(self, sample: object) -> None: ...


@dataclass(slots=True)
class PmcEightSerialTransport:
    """Serial transport for Explore Scientific PMC-Eight mounts.

    For iEXOS-100 / iEXOS-100-2, the programmer reference specifies:
    - 115200 baud
    - 8 data bits
    - 1 stop bit
    - no parity
    - no flow control
    """

    port: str = "/dev/ttyUSB0"
    baudrate: int = 115200
    timeout_sec: float = 2.0
    _serial: serial.Serial | None = field(init=False, default=None, repr=False)

    def connect(self) -> None:
        self._serial = serial.Serial(
            port=self.port,
            baudrate=self.baudrate,
            timeout=self.timeout_sec,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
        )

    def disconnect(self) -> None:
        if self._serial and self._serial.is_open:
            self._serial.close()

    def send(self, command: str) -> str:
        if not self._serial or not self._serial.is_open:
            raise RuntimeError("Serial transport not connected")
        self._serial.reset_input_buffer()
        self._serial.write(command.encode("ascii"))
        self._serial.flush()
        return self._serial.read(128).decode("ascii", errors="replace")


@dataclass(slots=True)
class PmcEightTcpTransport:
    """TCP/IP transport for PMC-Eight after the mount has been switched to TCP mode."""

    host: str = "192.168.47.1"
    port: int = 54372
    timeout_sec: float = 2.0
    _sock: socket.socket | None = field(init=False, default=None, repr=False)

    def connect(self) -> None:
        sock = socket.create_connection((self.host, self.port), timeout=self.timeout_sec)
        sock.settimeout(self.timeout_sec)
        self._sock = sock

    def disconnect(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None

    def send(self, command: str) -> str:
        if self._sock is None:
            raise RuntimeError("TCP transport not connected")
        self._sock.sendall(command.encode("ascii"))
        try:
            data = self._sock.recv(128)
        except socket.timeout:
            return ""
        return data.decode("ascii", errors="replace")


@dataclass(slots=True)
class PmcEightProtocol:
    """Protocol client for Explore Scientific PMC-Eight mounts.

    This uses the Explore Scientific command language (e.g. ESGp, ESPt, ESX, ESY),
    not LX200 commands.

    Notes on target conversion:
    - The point command expects internal axis target counts, not RA/Dec text.
    - The conversion below assumes a Northern Hemisphere German equatorial mount.
    - For iEXOS-100 / iEXOS-100-2, the commonly used RA/DEC step scale is 4,147,200
      counts per revolution. Make this configurable because firmware / driver setup may differ.
    - `longitude_deg` is east-positive; west longitudes should be negative.
    """

    transport: PmcEightSerialTransport | PmcEightTcpTransport
    longitude_deg: float
    latitude_deg: float = 0.0
    counts_per_revolution: int = 4_147_200
    northern_hemisphere: bool = True

    def connect(self) -> None:
        self.transport.connect()

    def disconnect(self) -> None:
        self.transport.disconnect()

    def _send(self, command: str) -> str:
        if not command.endswith("!"):
            raise ValueError("PMC-Eight commands must end with '!' ")
        return self.transport.send(command)

    @staticmethod
    def _to_hex24_signed(value: int) -> str:
        return f"{value & 0xFFFFFF:06X}"

    @staticmethod
    def _parse_hex24_signed(value: str) -> int:
        raw = int(value, 16)
        if raw & 0x800000:
            raw -= 0x1000000
        return raw

    def get_version(self) -> str:
        return self._send("ESGv!")

    def get_axis_position_counts(self, axis: int) -> int:
        response = self._send(f"ESGp{axis}!")
        prefix = f"ESGp{axis}"
        if not response.startswith(prefix) or not response.endswith("!"):
            raise RuntimeError(f"Unexpected ESGp response: {response!r}")
        return self._parse_hex24_signed(response[len(prefix):-1])

    def get_axis_target_counts(self, axis: int) -> int:
        response = self._send(f"ESGt{axis}!")
        prefix = f"ESGt{axis}"
        if not response.startswith(prefix) or not response.endswith("!"):
            raise RuntimeError(f"Unexpected ESGt response: {response!r}")
        return self._parse_hex24_signed(response[len(prefix):-1])

    def set_axis_position_counts(self, axis: int, counts: int) -> str:
        return self._send(f"ESSp{axis}{self._to_hex24_signed(counts)}!")

    def point_axis_to_counts(self, axis: int, counts: int) -> str:
        return self._send(f"ESPt{axis}{self._to_hex24_signed(counts)}!")

    def set_axis_slew_rate(self, axis: int, rate_hex: int) -> str:
        if not 0 <= rate_hex <= 0xFFFF:
            raise ValueError("Slew rate must fit in 4 hex digits")
        return self._send(f"ESSr{axis}{rate_hex:04X}!")

    def set_tracking_rate(self, counts_per_sidereal_second: int) -> str:
        if not 0 <= counts_per_sidereal_second <= 0xFFFF:
            raise ValueError("Tracking rate must fit in 4 hex digits")
        return self._send(f"ESTr{counts_per_sidereal_second:04X}!")

    def switch_interface(self) -> str:
        """Toggle between Wi‑Fi and serial interfaces using ESX!."""
        return self._send("ESX!")

    def switch_wifi_protocol(self) -> str:
        """Toggle between UDP and TCP Wi‑Fi protocols using ESY!."""
        return self._send("ESY!")

    @staticmethod
    def switch_wifi_protocol_via_udp(
        host: str = "192.168.47.1",
        port: int = 54372,
        timeout_sec: float = 1.0,
    ) -> None:
        """Send ESY! over UDP to toggle the Wi‑Fi stack between UDP and TCP mode.

        This is useful on iEXOS-100 / iEXOS-100-2 when the mount is still in its
        default ExploreStars UDP mode and you want to move it to TCP/IP mode.
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.settimeout(timeout_sec)
            sock.sendto(b"ESY!", (host, port))
        finally:
            sock.close()

    @staticmethod
    def _normalize_hours(hours: float) -> float:
        hours = math.fmod(hours, 24.0)
        if hours < 0:
            hours += 24.0
        return hours

    @staticmethod
    def _normalize_hour_angle(hours: float) -> float:
        hours = math.fmod(hours + 12.0, 24.0)
        if hours < 0:
            hours += 24.0
        return hours - 12.0

    @staticmethod
    def _julian_date(dt: datetime) -> float:
        if dt.tzinfo is None:
            raise ValueError("datetime must be timezone-aware")
        dt = dt.astimezone(timezone.utc)
        year = dt.year
        month = dt.month
        day = dt.day + (
            dt.hour
            + dt.minute / 60.0
            + dt.second / 3600.0
            + dt.microsecond / 3_600_000_000.0
        ) / 24.0
        if month <= 2:
            year -= 1
            month += 12
        a = year // 100
        b = 2 - a + (a // 4)
        return (
            int(365.25 * (year + 4716))
            + int(30.6001 * (month + 1))
            + day
            + b
            - 1524.5
        )

    def local_sidereal_time_hours(self, when_utc: datetime | None = None) -> float:
        when_utc = when_utc or datetime.now(timezone.utc)
        jd = self._julian_date(when_utc)
        t = (jd - 2451545.0) / 36525.0
        gmst_deg = (
            280.46061837
            + 360.98564736629 * (jd - 2451545.0)
            + 0.000387933 * (t**2)
            - (t**3) / 38710000.0
        )
        lst_deg = (gmst_deg + self.longitude_deg) % 360.0
        return lst_deg / 15.0

    def equatorial_to_mount_counts(
        self,
        ra_deg: float,
        dec_deg: float,
        when_utc: datetime | None = None,
        prefer_west_pointing_east: Optional[bool] = None,
    ) -> tuple[int, int]:
        """Convert sky coordinates to PMC-Eight axis counts.

        Assumptions:
        - Northern Hemisphere GEM geometry.
        - Park/reference position corresponds to (RA, DEC) motor counts of 0.
        - The target is on the currently valid side of the meridian.

        Returned tuple is (ra_axis_counts, dec_axis_counts).
        """
        if not self.northern_hemisphere:
            raise NotImplementedError(
                "This conversion is currently implemented for Northern Hemisphere GEMs only."
            )

        lst_hours = self.local_sidereal_time_hours(when_utc)
        ra_hours = self._normalize_hours(ra_deg / 15.0)
        ha_hours = self._normalize_hour_angle(lst_hours - ra_hours)

        counts_per_hour = self.counts_per_revolution / 24.0
        quarter_rev = self.counts_per_revolution / 4.0
        half_rev = self.counts_per_revolution / 2.0

        if prefer_west_pointing_east is None:
            west_pointing_east = ha_hours < 0
        else:
            west_pointing_east = prefer_west_pointing_east

        if west_pointing_east:
            ra_counts = int(round(quarter_rev + counts_per_hour * ha_hours))
            dec_counts = int(round(quarter_rev - (dec_deg / 180.0) * half_rev))
        else:
            ra_counts = int(round(-quarter_rev + counts_per_hour * ha_hours))
            dec_counts = int(round((dec_deg / 180.0) * half_rev - quarter_rev))

        return ra_counts, dec_counts

    def slew_to_radec(
        self,
        ra_deg: float,
        dec_deg: float,
        when_utc: datetime | None = None,
        prefer_west_pointing_east: Optional[bool] = None,
    ) -> tuple[str, str]:
        ra_counts, dec_counts = self.equatorial_to_mount_counts(
            ra_deg=ra_deg,
            dec_deg=dec_deg,
            when_utc=when_utc,
            prefer_west_pointing_east=prefer_west_pointing_east,
        )
        ra_response = self.point_axis_to_counts(0, ra_counts)
        dec_response = self.point_axis_to_counts(1, dec_counts)
        return ra_response, dec_response

    def sync_to_radec(
        self,
        ra_deg: float,
        dec_deg: float,
        when_utc: datetime | None = None,
        prefer_west_pointing_east: Optional[bool] = None,
    ) -> tuple[str, str]:
        """Hard-sync the controller by writing current axis position counts.

        This is a low-level sync that directly sets the controller's current axis position.
        It is not the same as a full plate-solve alignment model.
        """
        ra_counts, dec_counts = self.equatorial_to_mount_counts(
            ra_deg=ra_deg,
            dec_deg=dec_deg,
            when_utc=when_utc,
            prefer_west_pointing_east=prefer_west_pointing_east,
        )
        ra_response = self.set_axis_position_counts(0, ra_counts)
        dec_response = self.set_axis_position_counts(1, dec_counts)
        return ra_response, dec_response

    def send_coordinates(self, sample: object) -> None:
        """Compatibility wrapper for tracker code.

        Expected attributes on `sample`:
        - sample.ra_deg
        - sample.dec_deg
        Optional:
        - sample.timestamp_utc (timezone-aware datetime)
        - sample.observed_at_utc (timezone-aware datetime)
        """
        ra_deg = float(getattr(sample, "ra_deg"))
        dec_deg = float(getattr(sample, "dec_deg"))
        when_utc = getattr(sample, "timestamp_utc", None) or getattr(sample, "observed_at_utc", None)
        self.slew_to_radec(ra_deg=ra_deg, dec_deg=dec_deg, when_utc=when_utc)


def build_iexos100_serial_protocol(
    port: str,
    longitude_deg: float,
    latitude_deg: float = 0.0,
    counts_per_revolution: int = 4_147_200,
) -> PmcEightProtocol:
    transport = PmcEightSerialTransport(port=port)
    return PmcEightProtocol(
        transport=transport,
        longitude_deg=longitude_deg,
        latitude_deg=latitude_deg,
        counts_per_revolution=counts_per_revolution,
        northern_hemisphere=latitude_deg >= 0,
    )


def build_iexos100_tcp_protocol(
    longitude_deg: float,
    latitude_deg: float = 0.0,
    host: str = "192.168.47.1",
    port: int = 54372,
    counts_per_revolution: int = 4_147_200,
) -> PmcEightProtocol:
    transport = PmcEightTcpTransport(host=host, port=port)
    return PmcEightProtocol(
        transport=transport,
        longitude_deg=longitude_deg,
        latitude_deg=latitude_deg,
        counts_per_revolution=counts_per_revolution,
        northern_hemisphere=latitude_deg >= 0,
    )
