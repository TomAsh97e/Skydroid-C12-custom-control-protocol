"""Hardware example for a Skydroid C12 at its default address."""

import time

from skydroid_c12 import SkydroidCamera


def hold_motion(
    camera: SkydroidCamera,
    duration: float,
    *,
    yaw: int = 0,
    pitch: int = 0,
) -> None:
    """Refresh operator input while the library transmits motion in the background."""
    deadline = time.monotonic() + duration
    while time.monotonic() < deadline:
        camera.gimbal.set_yaw_speed(yaw)
        camera.gimbal.set_pitch_speed(pitch)
        time.sleep(0.05)
    camera.gimbal.stop()


def main() -> None:
    with SkydroidCamera() as camera:
        camera.take_photo()
        time.sleep(1)

        hold_motion(camera, 1.0, yaw=40)
        hold_motion(camera, 1.0, yaw=-40, pitch=30)

        camera.gimbal.center_yaw()
        time.sleep(2)
        camera.gimbal.look_down()
        time.sleep(2)
        camera.gimbal.center()

        camera.zoom.in_(duration=1.0)
        camera.zoom.out(duration=0.5)


if __name__ == "__main__":
    main()
