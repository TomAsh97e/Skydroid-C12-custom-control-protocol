# Skydroid C12 Python SDK

Unofficial Python library for UDP control of the **Skydroid C12**: yaw, pitch,
zoom, photos, and position presets. Python 3.10+, no runtime dependencies.
Includes background transmitters, an input watchdog, and offline tests.

## Reverse engineering

Wireshark on a separate PC and an Android PCAP app on the **SIYI MK32** did
not expose usable control traffic. A transparent Ethernet bridge finally did:

```text
SIYI MK32 → RF → Air Unit → Raspberry Pi Ethernet bridge → Skydroid C12
```

The bridge used a CM5-NANO-B, built-in Ethernet, a TP-Link USB Ethernet adapter,
and Ubuntu 24.04. Captured commands became the basis for the protocol encoder.

## Install

```bash
git clone https://github.com/TomAsh97e/Skydroid-C12-custom-control-protocol.git
cd Skydroid-C12-custom-control-protocol
python -m pip install -e .
```

## Usage

```python
import time
from skydroid_c12 import SkydroidCamera

with SkydroidCamera() as camera:
    camera.take_photo()
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        camera.gimbal.set_yaw_speed(40)
        time.sleep(0.05)
    camera.gimbal.stop()
    camera.gimbal.center()
    camera.zoom.in_(duration=1.0)
```

Motion uses velocity from `-127` to `127`, not absolute angles. Refresh input
within `command_timeout` (default: 0.3 s); otherwise the watchdog sends STOP.
Exiting `with` stops both axes and closes the transport.

Other controls: `set_pitch_speed()`, `move_left/right/up/down()`,
`stop_yaw()`, `stop_pitch()`, `center_yaw()`, `look_down()`, `zoom.out()`,
and `zoom.stop()`. For multiple network interfaces, pass `local_ip`.

## Protocol

Default source and destination UDP port: `5000`; destination: `192.168.144.108`.
Motion repeats every 50 ms, zoom every 28 ms. Each ASCII command ends with
`sum(base_command.encode("ascii")) & 0xFF` as two uppercase hex characters.
Speed uses a two's-complement byte (`80 → 50`, `-80 → B0`).

| Action | Base command (checksum added automatically) |
| --- | --- |
| Yaw / pitch | `#TPUG2wGSY{speed}` / `#TPUG2wGSP{speed}` |
| Zoom in / out | `#TPUD2wDZM0A` / `#TPUD2wDZM0B` |
| Center / center yaw / look down | `#TPUG2wPTZ05` / `#TPUG6wGAY000010` / `#TPUG2wPTZ02` |
| Photo | `#TPUD2wCAP01` (append CRLF after checksum) |

Bench-test with a clear movement area on an isolated network. UDP has no
execution confirmation or known authentication; firmware behavior may vary.
Network errors are raised to callers; background failures surface on the next
control call. One process controls one C12; telemetry and tracking are not implemented.

## Tests

```bash
python -m unittest discover -s tests -v
```

Tests run offline. `examples/basic_control.py` operates real hardware.

MIT License. Independent project, unaffiliated with Skydroid or SIYI.
