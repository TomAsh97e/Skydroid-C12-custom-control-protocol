import time
import unittest
from unittest.mock import patch

from skydroid_c12 import (
    CameraControl,
    GimbalControl,
    ProtocolEncoder,
    SkydroidCamera,
    UdpTransport,
    ZoomControl,
)


class FakeTransport:
    def __init__(self) -> None:
        self.packets: list[bytes] = []
        self.error: OSError | None = None
        self.closed = False

    def send(self, data: bytes) -> None:
        if self.error is not None:
            raise self.error
        self.packets.append(data)

    def close(self) -> None:
        self.closed = True


def wait_for(predicate, timeout: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


class ProtocolEncoderTests(unittest.TestCase):
    def test_known_frames(self) -> None:
        frames = (
            ("#TPUG2wGSYB0", False, b"#TPUG2wGSYB071"),
            ("#TPUG2wGSY50", False, b"#TPUG2wGSY5064"),
            ("#TPUG2wGSPB0", False, b"#TPUG2wGSPB068"),
            ("#TPUD2wDZM0A", False, b"#TPUD2wDZM0A65"),
            ("#TPUD2wDZM0B", False, b"#TPUD2wDZM0B66"),
            ("#TPUG2wPTZ05", False, b"#TPUG2wPTZ056F"),
            ("#TPUG6wGAY000010", False, b"#TPUG6wGAY00001012"),
            ("#TPUG2wPTZ02", False, b"#TPUG2wPTZ026C"),
            ("#TPUD2wCAP01", True, b"#TPUD2wCAP013E\r\n"),
        )
        for base, append_crlf, expected in frames:
            with self.subTest(base=base):
                self.assertEqual(
                    ProtocolEncoder.encode(base, append_crlf=append_crlf),
                    expected,
                )

    def test_speed_is_clamped_and_twos_complement_encoded(self) -> None:
        self.assertEqual(ProtocolEncoder.format_speed(-200), "81")
        self.assertEqual(ProtocolEncoder.format_speed(-80), "B0")
        self.assertEqual(ProtocolEncoder.format_speed(200), "7F")


class UdpTransportTests(unittest.TestCase):
    @patch("skydroid_c12.client.socket.socket")
    def test_binds_and_sends_from_observed_port(self, socket_factory) -> None:
        transport = UdpTransport("192.168.144.108", 5000)
        socket_factory.return_value.bind.assert_called_once_with(("", 5000))

        transport.send(b"frame")
        socket_factory.return_value.sendto.assert_called_once_with(
            b"frame", ("192.168.144.108", 5000)
        )
        transport.close()

    @patch("skydroid_c12.client.socket.socket")
    def test_send_error_reaches_caller(self, socket_factory) -> None:
        socket_factory.return_value.sendto.side_effect = OSError("network down")
        transport = UdpTransport("192.168.144.108", 5000)
        with self.assertRaisesRegex(OSError, "network down"):
            transport.send(b"frame")
        transport.close()

    @patch("skydroid_c12.client.socket.socket")
    def test_bind_error_closes_socket(self, socket_factory) -> None:
        socket_factory.return_value.bind.side_effect = OSError("port in use")
        with self.assertRaisesRegex(OSError, "port in use"):
            UdpTransport("192.168.144.108", 5000)
        socket_factory.return_value.close.assert_called_once_with()

    def test_rejects_invalid_port(self) -> None:
        with self.assertRaises(ValueError):
            UdpTransport("192.168.144.108", 0)


class CameraControlTests(unittest.TestCase):
    def test_photo_uses_crlf_frame(self) -> None:
        transport = FakeTransport()
        CameraControl(transport).take_photo()
        self.assertEqual(transport.packets, [b"#TPUD2wCAP013E\r\n"])


class GimbalControlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.transport = FakeTransport()
        self.gimbal = GimbalControl(self.transport, timeout=0.1)
        self.addCleanup(self._close)

    def _close(self) -> None:
        self.transport.error = None
        self.gimbal.close()

    def test_motion_stop_and_presets(self) -> None:
        self.gimbal.set_yaw_speed(-80)
        self.assertTrue(
            wait_for(lambda: b"#TPUG2wGSYB071" in self.transport.packets)
        )

        self.gimbal.center()
        self.assertEqual(
            self.transport.packets[-3:],
            [b"#TPUG2wGSY005F", b"#TPUG2wGSP0056", b"#TPUG2wPTZ056F"],
        )

    def test_watchdog_sends_stop(self) -> None:
        self.gimbal.move_right(80)
        self.assertTrue(
            wait_for(lambda: b"#TPUG2wGSY5064" in self.transport.packets)
        )
        self.assertTrue(
            wait_for(lambda: b"#TPUG2wGSY005F" in self.transport.packets)
        )
        self.assertIn(b"#TPUG2wGSP0056", self.transport.packets)

    def test_close_sends_stop_and_rejects_new_commands(self) -> None:
        self.transport.packets.clear()
        self.gimbal.close()
        self.assertEqual(
            self.transport.packets,
            [b"#TPUG2wGSY005F", b"#TPUG2wGSP0056"],
        )
        with self.assertRaisesRegex(RuntimeError, "closed"):
            self.gimbal.move_right()

    def test_background_network_error_is_exposed(self) -> None:
        self.gimbal.move_right()
        with self.assertLogs("skydroid_c12.client", level="ERROR"):
            self.transport.error = OSError("network down")
            self.assertTrue(wait_for(lambda: not self.gimbal._thread.is_alive()))
        with self.assertRaisesRegex(ConnectionError, "network error"):
            self.gimbal.move_right()


class ZoomControlTests(unittest.TestCase):
    def test_timed_zoom_stops_and_close_rejects_commands(self) -> None:
        transport = FakeTransport()
        zoom = ZoomControl(transport)
        zoom.in_(duration=0.06)
        self.assertIn(b"#TPUD2wDZM0A65", transport.packets)
        self.assertIsNone(zoom._zoom_mode)

        zoom.close()
        with self.assertRaisesRegex(RuntimeError, "closed"):
            zoom.out()

    def test_rejects_negative_duration(self) -> None:
        zoom = ZoomControl(FakeTransport())
        self.addCleanup(zoom.close)
        with self.assertRaises(ValueError):
            zoom.in_(duration=-1)

    def test_background_network_error_is_exposed(self) -> None:
        transport = FakeTransport()
        zoom = ZoomControl(transport)
        zoom.in_()
        with self.assertLogs("skydroid_c12.client", level="ERROR"):
            transport.error = OSError("network down")
            self.assertTrue(wait_for(lambda: not zoom._thread.is_alive()))
        with self.assertRaisesRegex(ConnectionError, "network error"):
            zoom.in_()
        zoom.close()


class SkydroidCameraTests(unittest.TestCase):
    def test_requires_connection(self) -> None:
        camera = SkydroidCamera()
        with self.assertRaisesRegex(RuntimeError, "not connected"):
            camera.take_photo()

    def test_context_manager_owns_all_resources(self) -> None:
        transport = FakeTransport()
        with patch("skydroid_c12.client.UdpTransport", return_value=transport):
            camera = SkydroidCamera()
            with camera:
                self.assertTrue(camera.connected)
                camera.take_photo()
            self.assertFalse(camera.connected)

        self.assertTrue(transport.closed)
        self.assertIn(b"#TPUD2wCAP013E\r\n", transport.packets)
        self.assertEqual(
            transport.packets[-2:],
            [b"#TPUG2wGSY005F", b"#TPUG2wGSP0056"],
        )

    def test_close_releases_resources_after_stop_error(self) -> None:
        transport = FakeTransport()
        with patch("skydroid_c12.client.UdpTransport", return_value=transport):
            camera = SkydroidCamera()
            camera.connect()
            transport.error = OSError("network down")
            with self.assertRaisesRegex(OSError, "network down"):
                camera.close()

        self.assertFalse(camera.connected)
        self.assertTrue(transport.closed)


if __name__ == "__main__":
    unittest.main()
