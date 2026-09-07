"""Testy sterowania bez komunikacji z kamerą."""
import time
import unittest
from unittest.mock import patch
from skydroid_camera import GimbalControl, ProtocolEncoder, UdpTransport

class CameraTests(unittest.TestCase):
    def setUp(self):
        self.packets = []
        transport = type('Transport', (), {'send': lambda _, data: self.packets.append(data)})()
        self.g = GimbalControl(transport, timeout=0.3)
        self.addCleanup(self.g.close)

    def test_frames(self):
        for base, expected in [('#TPUG2wGSYB0', b'#TPUG2wGSYB071'), ('#TPUG2wGSY50', b'#TPUG2wGSY5064'), ('#TPUD2wDZM0A', b'#TPUD2wDZM0A65'), ('#TPUD2wDZM0B', b'#TPUD2wDZM0B66')]:
            self.assertEqual(ProtocolEncoder.encode(base), expected)

    def test_port(self):
        with patch('skydroid_camera.socket.socket') as sock:
            t = UdpTransport('192.168.144.108', 5000)
            sock.return_value.bind.assert_called_once_with(('', 5000))
            t.close()

    def test_independent_stop(self):
        self.g.move_right(80)
        self.g.move_up(80)
        time.sleep(0.07)
        self.assertIn(b'#TPUG2wGSY5064', self.packets)
        self.g.stop_yaw()
        self.assertEqual(self.packets[-1], b'#TPUG2wGSY005F')
        start = len(self.packets)
        time.sleep(0.07)
        self.assertIn(b'#TPUG2wGSP505B', self.packets[start:])
        self.assertNotIn(b'#TPUG2wGSY5064', self.packets[start:])

    def test_watchdog(self):
        self.g.move_right(80)
        deadline = time.monotonic() + 2
        while b'#TPUG2wGSY005F' not in self.packets and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertIn(b'#TPUG2wGSY5064', self.packets)
        self.assertIn(b'#TPUG2wGSY005F', self.packets)
        self.assertIn(b'#TPUG2wGSP0056', self.packets)

    def test_center_order(self):
        self.g.move_right(80)
        self.g.center()
        self.assertEqual(self.packets[-3:], [b'#TPUG2wGSY005F', b'#TPUG2wGSP0056', b'#TPUG2wPTZ056F'])
        time.sleep(0.07)
        self.assertEqual(self.packets[-1], b'#TPUG2wPTZ056F')

    def test_close(self):
        self.g.move_right(80)
        self.g.close()
        self.assertEqual(self.packets[-2:], [b'#TPUG2wGSY005F', b'#TPUG2wGSP0056'])
        count = len(self.packets)
        self.g.close()
        time.sleep(0.07)
        self.assertEqual(len(self.packets), count)

if __name__ == '__main__':
    unittest.main()
