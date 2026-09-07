import socket
import threading
import time

class SkydroidGimbal:
    """
    Biblioteka do sterowania gimbalem Skydroid C12 przez UDP.
    Działa w oparciu o wątek w tle, który cyklicznie wysyła komendy (co 0.05s),
    co zapobiega blokowaniu głównych pętli programów (np. ROS 2, AI).
    """
    
    # Słownik zdekodowanych pakietów
    COMMANDS = {
        'yaw_right_20': b'#TPUG2wGSY1464',
        'yaw_left_20':  b'#TPUG2wGSYEC87',
        'pitch_up_20':  b'#TPUG2wGSP145B',
        'pitch_down_20':b'#TPUG2wGSPEC7E',
        
        'yaw_right_80': b'#TPUG2wGSY5064',
        'yaw_left_80':  b'#TPUG2wGSYB071',
        'pitch_up_80':  b'#TPUG2wGSP505B',
        'pitch_down_80':b'#TPUG2wGSPB068',
        
        'stop_yaw':     b'#TPUG2wGSY005F',
        'stop_pitch':   b'#TPUG2wGSP0056',
        
        'center':       b'#TPUG2wPTZ056F'
    }

    def __init__(self, ip='192.168.144.108', port=5000, hz=20.0):
        self.ip = ip
        self.port = port
        self.sleep_time = 1.0 / hz
        
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Bindowanie nie jest wymagane do wysyłania, ale wymusza konkretny port źródłowy jeśli potrzeba.
        # W Twoim skrypcie 'nc -p 5000' oznacza, że wysyłasz z portu 5000.
        self.sock.bind(('', self.port)) 
        
        # Stany obecnego ruchu
        self._current_yaw_cmd = None
        self._current_pitch_cmd = None
        
        # Kontrola wątku
        self._running = True
        self._lock = threading.Lock()
        
        self._thread = threading.Thread(target=self._transmit_loop, daemon=True)
        self._thread.start()
        print(f"[SkydroidGimbal] Zainicjowano połączenie {self.ip}:{self.port} w tle.")

    def _transmit_loop(self):
        """Wewnętrzna pętla wątku wysyłająca komendy co zadaną częstotliwość."""
        while self._running:
            with self._lock:
                yaw_cmd = self._current_yaw_cmd
                pitch_cmd = self._current_pitch_cmd

            try:
                if yaw_cmd:
                    self.sock.sendto(yaw_cmd, (self.ip, self.port))
                if pitch_cmd:
                    self.sock.sendto(pitch_cmd, (self.ip, self.port))
            except Exception as e:
                print(f"[SkydroidGimbal] Błąd sieci: {e}")
                
            time.sleep(self.sleep_time)

    def set_yaw(self, direction, speed=20):
        """
        Ustawia ciągły obrót poziomy.
        :param direction: 'right', 'left' lub 'stop'
        :param speed: 20 lub 80
        """
        with self._lock:
            if direction == 'stop':
                self._current_yaw_cmd = None
                self._send_immediate(self.COMMANDS['stop_yaw'])
            else:
                cmd_key = f"yaw_{direction}_{speed}"
                if cmd_key in self.COMMANDS:
                    self._current_yaw_cmd = self.COMMANDS[cmd_key]
                else:
                    raise ValueError(f"Nieznana komenda YAW: {cmd_key}")

    def set_pitch(self, direction, speed=20):
        """
        Ustawia ciągły obrót pionowy.
        :param direction: 'up', 'down' lub 'stop'
        :param speed: 20 lub 80
        """
        with self._lock:
            if direction == 'stop':
                self._current_pitch_cmd = None
                self._send_immediate(self.COMMANDS['stop_pitch'])
            else:
                cmd_key = f"pitch_{direction}_{speed}"
                if cmd_key in self.COMMANDS:
                    self._current_pitch_cmd = self.COMMANDS[cmd_key]
                else:
                    raise ValueError(f"Nieznana komenda PITCH: {cmd_key}")

    def stop_all(self):
        """Zatrzymuje ruch w obu osiach."""
        self.set_yaw('stop')
        self.set_pitch('stop')

    def center(self):
        """Centruje gimbal."""
        self.stop_all()
        # Wysyłamy parę razy dla pewności (UDP potrafi zgubić pakiet)
        for _ in range(3):
            self._send_immediate(self.COMMANDS['center'])
            time.sleep(0.05)

    def _send_immediate(self, payload):
        """Pomocnicza funkcja do natychmiastowego wysłania ramki z pominięciem kolejki."""
        self.sock.sendto(payload, (self.ip, self.port))

    def close(self):
        """Kończy wątek wysyłający i zamyka gniazdo."""
        self._running = False
        self._thread.join(timeout=1.0)
        self.sock.close()
        print("[SkydroidGimbal] Połączenie zamknięte.")
