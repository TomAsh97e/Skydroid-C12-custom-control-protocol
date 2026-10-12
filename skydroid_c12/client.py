"""UDP controls for the Skydroid C12 gimbal and camera."""

import logging
import socket
import threading
import time


LOGGER = logging.getLogger(__name__)


class ProtocolEncoder:
    """Build ASCII protocol frames with their one-byte checksum."""

    @staticmethod
    def encode(base_command: str, append_crlf: bool = False) -> bytes:
        """Append the uppercase modulo-256 checksum and optional CRLF."""
        checksum = sum(base_command.encode("ascii")) & 0xFF
        command = f"{base_command}{checksum:02X}"
        if append_crlf:
            command += "\r\n"
        return command.encode("ascii")

    @staticmethod
    def format_speed(speed: int) -> str:
        """Encode a speed clamped to -127..127 as an unsigned byte."""
        speed = max(-127, min(127, int(speed)))
        return f"{speed & 0xFF:02X}"


class UdpTransport:
    """Send protocol frames from the observed UDP source port."""

    def __init__(
        self, ip: str, port: int, local_ip: str | None = None
    ) -> None:
        if (
            isinstance(port, bool)
            or not isinstance(port, int)
            or not 1 <= port <= 65535
        ):
            raise ValueError("port must be an integer between 1 and 65535")

        self.ip = ip
        self.port = port
        self.local_ip = local_ip
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        try:
            self.sock.bind((local_ip or "", port))
        except OSError:
            self.sock.close()
            raise

    def send(self, data: bytes) -> None:
        """Send one frame, propagating network errors to the caller."""
        self.sock.sendto(data, (self.ip, self.port))

    def close(self) -> None:
        self.sock.close()


class CameraControl:
    """Single-shot camera commands."""

    def __init__(self, transport: UdpTransport) -> None:
        self._transport = transport

    def take_photo(self) -> None:
        """Trigger a photo; this command uniquely requires a trailing CRLF."""
        self._transport.send(
            ProtocolEncoder.encode("#TPUD2wCAP01", append_crlf=True)
        )
        LOGGER.info("Photo command sent")


class GimbalControl:
    """Control yaw and pitch with a background transmitter and input watchdog."""

    def __init__(
        self,
        transport: UdpTransport,
        timeout: float = 0.3,
        send_stop_on_timeout: bool = True,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be greater than zero")

        self._transport = transport
        self.timeout = timeout
        self.send_stop_on_timeout = send_stop_on_timeout
        self._yaw_speed = 0
        self._pitch_speed = 0
        self._last_update = time.monotonic()
        self._last_error: OSError | None = None
        self._lock = threading.RLock()
        self._running = True
        self._closed = False
        self._thread = threading.Thread(
            target=self._transmit_loop,
            name="skydroid-gimbal",
            daemon=True,
        )
        self._thread.start()

    def _raise_if_unavailable(self) -> None:
        if self._last_error is not None:
            raise ConnectionError(
                "gimbal transmitter stopped after a network error"
            ) from self._last_error
        if self._closed or not self._running:
            raise RuntimeError("gimbal control is closed")

    def _send_axis(self, axis: str, speed: int) -> None:
        value = ProtocolEncoder.format_speed(speed)
        self._transport.send(ProtocolEncoder.encode(f"#TPUG2wGS{axis}{value}"))

    def _send_stops(self, axes: tuple[str, ...]) -> None:
        first_error: OSError | None = None
        for axis in axes:
            try:
                self._send_axis(axis, 0)
            except OSError as error:
                first_error = first_error or error
        if first_error is not None:
            raise first_error

    def _transmit_loop(self) -> None:
        try:
            while True:
                with self._lock:
                    if not self._running:
                        return
                    if (
                        self.send_stop_on_timeout
                        and time.monotonic() - self._last_update > self.timeout
                        and (self._yaw_speed or self._pitch_speed)
                    ):
                        self._yaw_speed = 0
                        self._pitch_speed = 0
                        self._send_stops(("Y", "P"))
                    else:
                        if self._yaw_speed:
                            self._send_axis("Y", self._yaw_speed)
                        if self._pitch_speed:
                            self._send_axis("P", self._pitch_speed)
                time.sleep(0.05)
        except OSError as error:
            with self._lock:
                self._last_error = error
                self._running = False
            LOGGER.error("Gimbal transmitter stopped: %s", error)

    def _update_speed(self, yaw: int | None = None, pitch: int | None = None) -> None:
        with self._lock:
            self._raise_if_unavailable()
            stop_axes = []
            for axis, speed, attribute in (
                ("Y", yaw, "_yaw_speed"),
                ("P", pitch, "_pitch_speed"),
            ):
                if speed is None:
                    continue
                speed = max(-127, min(127, int(speed)))
                setattr(self, attribute, speed)
                if speed == 0:
                    stop_axes.append(axis)
            self._last_update = time.monotonic()
            self._send_stops(tuple(stop_axes))

    def set_yaw_speed(self, speed: int) -> None:
        self._update_speed(yaw=speed)

    def set_pitch_speed(self, speed: int) -> None:
        self._update_speed(pitch=speed)

    def move_right(self, speed: int = 40) -> None:
        self.set_yaw_speed(abs(speed))

    def move_left(self, speed: int = 40) -> None:
        self.set_yaw_speed(-abs(speed))

    def move_up(self, speed: int = 30) -> None:
        self.set_pitch_speed(abs(speed))

    def move_down(self, speed: int = 30) -> None:
        self.set_pitch_speed(-abs(speed))

    def stop_yaw(self) -> None:
        self.set_yaw_speed(0)

    def stop_pitch(self) -> None:
        self.set_pitch_speed(0)

    def stop(self) -> None:
        self._update_speed(yaw=0, pitch=0)

    def center(self) -> None:
        """Stop both axes and request the neutral position."""
        with self._lock:
            self.stop()
            self._transport.send(ProtocolEncoder.encode("#TPUG2wPTZ05"))

    def center_yaw(self) -> None:
        """Stop yaw and request its neutral position without changing pitch."""
        with self._lock:
            self.stop_yaw()
            self._transport.send(ProtocolEncoder.encode("#TPUG6wGAY000010"))

    def look_down(self) -> None:
        """Stop both axes and request the straight-down preset."""
        with self._lock:
            self.stop()
            self._transport.send(ProtocolEncoder.encode("#TPUG2wPTZ02"))

    def close(self) -> None:
        """Send an immediate stop and terminate the transmitter thread."""
        with self._lock:
            if self._closed:
                return
            error: OSError | None = None
            try:
                self._send_stops(("Y", "P"))
            except OSError as caught:
                error = caught
            finally:
                self._yaw_speed = 0
                self._pitch_speed = 0
                self._running = False
                self._closed = True
        self._thread.join()
        if error is not None:
            raise error


class ZoomControl:
    """Transmit continuous zoom commands at approximately 35 Hz."""

    def __init__(self, transport: UdpTransport) -> None:
        self._transport = transport
        self._zoom_mode: str | None = None
        self._last_error: OSError | None = None
        self._lock = threading.Lock()
        self._running = True
        self._closed = False
        self._thread = threading.Thread(
            target=self._transmit_loop,
            name="skydroid-zoom",
            daemon=True,
        )
        self._thread.start()

    def _raise_if_unavailable(self) -> None:
        if self._last_error is not None:
            raise ConnectionError(
                "zoom transmitter stopped after a network error"
            ) from self._last_error
        if self._closed or not self._running:
            raise RuntimeError("zoom control is closed")

    def _transmit_loop(self) -> None:
        try:
            while True:
                with self._lock:
                    if not self._running:
                        return
                    if self._zoom_mode == "in":
                        self._transport.send(
                            ProtocolEncoder.encode("#TPUD2wDZM0A")
                        )
                    elif self._zoom_mode == "out":
                        self._transport.send(
                            ProtocolEncoder.encode("#TPUD2wDZM0B")
                        )
                time.sleep(0.028)
        except OSError as error:
            with self._lock:
                self._last_error = error
                self._running = False
            LOGGER.error("Zoom transmitter stopped: %s", error)

    def _start(self, mode: str, duration: float | None) -> None:
        if duration is not None and duration < 0:
            raise ValueError("duration must be zero or greater")
        with self._lock:
            self._raise_if_unavailable()
            self._zoom_mode = mode
        if duration is not None:
            try:
                time.sleep(duration)
            finally:
                self.stop()

    def in_(self, duration: float | None = None) -> None:
        """Zoom in until stopped or until the optional duration elapses."""
        self._start("in", duration)

    def out(self, duration: float | None = None) -> None:
        """Zoom out until stopped or until the optional duration elapses."""
        self._start("out", duration)

    def stop(self) -> None:
        """Stop zoom by ending its command stream."""
        with self._lock:
            self._raise_if_unavailable()
            self._zoom_mode = None

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._zoom_mode = None
            self._running = False
            self._closed = True
        self._thread.join()


class SkydroidCamera:
    """High-level owner of the UDP transport and all camera controls."""

    def __init__(
        self,
        ip: str = "192.168.144.108",
        port: int = 5000,
        local_ip: str | None = None,
        command_timeout: float = 0.3,
        send_stop_on_timeout: bool = True,
    ) -> None:
        self._ip = ip
        self._port = port
        self._local_ip = local_ip
        self._command_timeout = command_timeout
        self._send_stop_on_timeout = send_stop_on_timeout
        self._transport: UdpTransport | None = None
        self._camera: CameraControl | None = None
        self._gimbal: GimbalControl | None = None
        self._zoom: ZoomControl | None = None

    @property
    def connected(self) -> bool:
        return self._transport is not None

    @property
    def camera(self) -> CameraControl:
        if self._camera is None:
            raise RuntimeError("camera is not connected")
        return self._camera

    @property
    def gimbal(self) -> GimbalControl:
        if self._gimbal is None:
            raise RuntimeError("camera is not connected")
        return self._gimbal

    @property
    def zoom(self) -> ZoomControl:
        if self._zoom is None:
            raise RuntimeError("camera is not connected")
        return self._zoom

    def connect(self) -> None:
        """Open the UDP transport and start both transmitter threads."""
        if self.connected:
            return

        transport = UdpTransport(self._ip, self._port, self._local_ip)
        gimbal: GimbalControl | None = None
        try:
            camera = CameraControl(transport)
            gimbal = GimbalControl(
                transport,
                self._command_timeout,
                self._send_stop_on_timeout,
            )
            zoom = ZoomControl(transport)
        except Exception:
            if gimbal is not None:
                try:
                    gimbal.close()
                except OSError:
                    pass
            transport.close()
            raise

        self._transport = transport
        self._camera = camera
        self._gimbal = gimbal
        self._zoom = zoom
        LOGGER.info("UDP control ready for %s:%s", self._ip, self._port)

    def take_photo(self) -> None:
        self.camera.take_photo()

    def close(self) -> None:
        """Stop controls and release every resource, even if one close fails."""
        first_error: Exception | None = None
        for resource in (self._gimbal, self._zoom, self._transport):
            if resource is None:
                continue
            try:
                resource.close()
            except Exception as error:
                first_error = first_error or error

        self._transport = None
        self._camera = None
        self._gimbal = None
        self._zoom = None
        if first_error is not None:
            raise first_error

    def __enter__(self) -> "SkydroidCamera":
        self.connect()
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()
