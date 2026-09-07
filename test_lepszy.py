import time
from skydroid_camera import SkydroidCamera

def hold_motion(camera, duration, yaw, pitch=0):
    deadline = time.monotonic() + duration
    while time.monotonic() < deadline:
        camera.gimbal.set_yaw_speed(yaw)
        camera.gimbal.set_pitch_speed(pitch)
        time.sleep(0.05)
    camera.gimbal.stop()


def main():
    camera = SkydroidCamera(
        ip="192.168.144.108",
        port=5000,
        local_ip=None, # Pozostaw None, jeśli używasz domyślnego interfejsu sieciowego (lub "192.168.144.21")
        command_timeout=0.3,
        send_stop_on_timeout=True,
    )

    camera.connect()

    try:
        # 1. Zrobienie zdjęcia
        camera.take_photo()
        time.sleep(1)

        # 2. Ruchy testowe (dzięki wątkom w tle komendy nie blokują działania pętli głównej)
        print("Ruch w prawo...")
        hold_motion(camera, 1.0, yaw=40)
    
        print("Ruch po skosie: lewo-góra...")
        hold_motion(camera, 1.0, yaw=-40, pitch=30)

        # 3. Zatrzymanie bezpośrednie
        print("Zatrzymanie...")
        camera.gimbal.stop()
        time.sleep(1)

        # 4. Presety (automatycznie zatrzymują bieżący ruch)
        print("Centrowanie samej osi YAW...")
        camera.gimbal.center_yaw()
        time.sleep(2)
    
        print("Patrzenie w dół...")
        camera.gimbal.look_down()
        time.sleep(2)
    
        print("Pełne centrowanie...")
        camera.gimbal.center()
        time.sleep(2)

        # 5. Zoom (Działający synchronicznie na zadany czas)
        print("Zoom IN...")
        camera.zoom.in_(duration=1.0)
    
        print("Zoom OUT...")
        camera.zoom.out(duration=0.5)

        # 6. Test Watchdoga
        print("Test Watchdoga - Startujemy ruch i zypiamy wątek na 2 sek bez aktualizacji...")
        camera.gimbal.move_right(80)
        time.sleep(2.0) # Po 0.3s GimbalControl automatycznie wyśle sygnał STOP!
        print("Program wznowiony, ruch powinien był się zatrzymać chwilę wcześniej.")

    finally:
        camera.close()

if __name__ == "__main__":
    main()
