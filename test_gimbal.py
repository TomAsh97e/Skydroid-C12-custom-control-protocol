import time
from skydroid_gimbal import SkydroidGimbal

def main():
    gimbal = SkydroidGimbal()

    print("Test: Powolny obrót w prawo (1 sekunda)...")
    gimbal.set_yaw('right', speed=20)
    time.sleep(1.0) # Twój kod w tym czasie może robić coś innego (np. klatka z kamery)
    
    print("Test: Szybki ruch w górę i w lewo (po przekątnej)...")
    gimbal.set_yaw('left', speed=80)
    gimbal.set_pitch('up', speed=80)
    time.sleep(0.5)
    
    print("Test: Zatrzymanie...")
    gimbal.stop_all()
    time.sleep(1.0)
    
    print("Test: Centrowanie...")
    gimbal.center()
    time.sleep(1.0)
    
    gimbal.close()

if __name__ == '__main__':
    main()
