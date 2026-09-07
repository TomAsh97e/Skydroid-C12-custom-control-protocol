import socket
import threading
import time

class ProtocolEncoder:
    """Odpowiada za generowanie ramek z sumą kontrolną."""
    
    @staticmethod
    def encode(base_command: str, append_crlf: bool = False) -> bytes:
        """
        Oblicza sumę kontrolną (modulo 256) ze znaków ASCII 
        i dołącza ją jako dwuznakowy hex na końcu komendy.
        """
        checksum = sum(base_command.encode("ascii")) & 0xFF
        command = f"{base_command}{checksum:02X}"
        if append_crlf:
            command += "\r\n"
        return command.encode("ascii")

    @staticmethod
    def format_speed(speed: int) -> str:
        """Koduje prędkość (od -127 do +127) na postać szesnastkową."""
        speed = max(-127, min(127, int(speed)))
        encoded = speed & 0xFF
        return f"{encoded:02X}"


class UdpTransport:
    """Zarządza gniazdem sieciowym UDP do komunikacji z kamerą."""
    
    def __init__(self, ip: str, port: int, local_ip: str = None):
        self.ip = ip
        self.port = port
        self.local_ip = local_ip
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        try:
            self.sock.bind((self.local_ip or "", self.port))
        except OSError:
            self.sock.close()
            raise
            
    def send(self, data: bytes):
        try:
            self.sock.sendto(data, (self.ip, self.port))
        except Exception as e:
            print(f"[UdpTransport] Błąd wysyłania: {e}")

    def close(self):
        self.sock.close()


class CameraControl:
    """Odpowiada za funkcje samej kamery (np. zdjęcia, nagrywanie)."""
    
    def __init__(self, transport: UdpTransport):
        self._transport = transport

    def take_photo(self):
        """Wykonywanie zdjęcia. Wymaga znaków nowej linii na końcu."""
        # Baza komendy: #TPUD2wCAP01 -> wygeneruje #TPUD2wCAP013E\r\n
        cmd = ProtocolEncoder.encode("#TPUD2wCAP01", append_crlf=True)
        self._transport.send(cmd)
        print("[CameraControl] Wysłano polecenie zdjęcia.")


class GimbalControl:
    """Odpowiada za sterowanie osiami Yaw oraz Pitch z wbudowanym watchdogiem."""
    
    def __init__(self, transport: UdpTransport, timeout: float = 0.3, send_stop_on_timeout: bool = True):
        self._transport = transport
        self.timeout = timeout
        self.send_stop_on_timeout = send_stop_on_timeout
        
        # Stany prędkości
        self._yaw_speed = 0
        self._pitch_speed = 0
        self._last_update = time.monotonic()
        
        self._lock = threading.RLock()

        # Kontrola wątku 20 Hz
        self._running = True
        self._thread = threading.Thread(target=self._transmit_loop, daemon=True)
        self._thread.start()

    def _send_axis(self, axis, speed):
        value = ProtocolEncoder.format_speed(speed)
        self._transport.send(ProtocolEncoder.encode(f"#TPUG2wGS{axis}{value}"))

    def _transmit_loop(self):
        while self._running:
            with self._lock:
                if not self._running:
                    break
                if (self.send_stop_on_timeout
                        and time.monotonic() - self._last_update > self.timeout
                        and (self._yaw_speed or self._pitch_speed)):
                    self.stop()
                if self._yaw_speed:
                    self._send_axis("Y", self._yaw_speed)
                if self._pitch_speed:
                    self._send_axis("P", self._pitch_speed)
            time.sleep(0.05)

    def _update_speed(self, yaw: int = None, pitch: int = None):
        with self._lock:
            if not self._running:
                raise RuntimeError("Sterowanie gimbalem jest zamknięte")
            for axis, speed, attr in (("Y", yaw, "_yaw_speed"),
                                      ("P", pitch, "_pitch_speed")):
                if speed is not None:
                    speed = max(-127, min(127, int(speed)))
                    setattr(self, attr, speed)
                    if speed == 0:
                        self._send_axis(axis, 0)
            self._last_update = time.monotonic()

    # --- API Niskopoziomowe ---
    def set_yaw_speed(self, speed: int):
        self._update_speed(yaw=speed)

    def set_pitch_speed(self, speed: int):
        self._update_speed(pitch=speed)

    # --- API Wysokopoziomowe Ruchu ---
    def move_right(self, speed: int = 40): self.set_yaw_speed(abs(speed))
    def move_left(self, speed: int = 40):  self.set_yaw_speed(-abs(speed))
    def move_up(self, speed: int = 30):    self.set_pitch_speed(abs(speed))
    def move_down(self, speed: int = 30):  self.set_pitch_speed(-abs(speed))

    def stop_yaw(self): self.set_yaw_speed(0)
    def stop_pitch(self): self.set_pitch_speed(0)
    def stop(self): self._update_speed(yaw=0, pitch=0)

    # --- Presety pozycjonowania (jednorazowe) ---
    def center(self):
        """Pełne centrowanie osi."""
        with self._lock:
            self.stop()
            self._transport.send(ProtocolEncoder.encode("#TPUG2wPTZ05"))

    def center_yaw(self):
        """Centrowanie tylko osi YAW (poziomej)."""
        with self._lock:
            self.stop_yaw()
            self._transport.send(ProtocolEncoder.encode("#TPUG6wGAY000010"))

    def look_down(self):
        """Ustawienie kamery pionowo w dół."""
        with self._lock:
            self.stop()
            self._transport.send(ProtocolEncoder.encode("#TPUG2wPTZ02"))

    def close(self):
        with self._lock:
            if not self._running:
                return
            self.stop()
            self._running = False
        self._thread.join()


class ZoomControl:
    """Odpowiada za płynne przybliżanie i oddalanie (~35 Hz)."""
    
    def __init__(self, transport: UdpTransport):
        self._transport = transport
        self._zoom_mode = None  # 'in', 'out' lub None
        
        self._running = True
        self._thread = threading.Thread(target=self._transmit_loop, daemon=True)
        self._thread.start()

    def _transmit_loop(self):
        """Wątek cykliczny wysyłający ramki (~35 Hz / co 28 ms)."""
        while self._running:
            if self._zoom_mode == 'in':
                self._transport.send(ProtocolEncoder.encode("#TPUD2wDZM0A"))
            elif self._zoom_mode == 'out':
                self._transport.send(ProtocolEncoder.encode("#TPUD2wDZM0B"))
                
            time.sleep(0.028)

    def in_(self, duration: float = None):
        """
        Przybliża obraz.
        Jeżeli 'duration' jest podane, blokuje wątek na ten czas i automatycznie zatrzymuje.
        """
        self._zoom_mode = 'in'
        if duration is not None:
            try:
                time.sleep(max(0, duration))
            finally:
                self.stop()

    def out(self, duration: float = None):
        """
        Oddala obraz.
        Jeżeli 'duration' jest podane, blokuje wątek na ten czas i automatycznie zatrzymuje.
        """
        self._zoom_mode = 'out'
        if duration is not None:
            try:
                time.sleep(max(0, duration))
            finally:
                self.stop()

    def stop(self):
        """Zatrzymuje akcję zoomowania."""
        self._zoom_mode = None

    def close(self):
        self._running = False
        self._thread.join(timeout=1.0)


class SkydroidCamera:
    """Główna klasa orkiestratora skupiająca wszystkie podsystemy."""
    
    def __init__(self, ip: str = "192.168.144.108", port: int = 5000, 
                 local_ip: str = None, command_timeout: float = 0.3, send_stop_on_timeout: bool = True):
        self._ip = ip
        self._port = port
        self._local_ip = local_ip
        
        self._transport = None
        self.camera = None
        self.gimbal = None
        self.zoom = None
        
        self._command_timeout = command_timeout
        self._send_stop_on_timeout = send_stop_on_timeout

    def connect(self):
        """Inicjuje połączenie sieciowe oraz wątki sterujące."""
        if self._transport is not None:
            return
        self._transport = UdpTransport(self._ip, self._port, self._local_ip)
        self.camera = CameraControl(self._transport)
        self.gimbal = GimbalControl(self._transport, self._command_timeout, self._send_stop_on_timeout)
        self.zoom = ZoomControl(self._transport)
        print(f"[SkydroidCamera] UDP gotowe do wysyłania do {self._ip}:{self._port}; brak potwierdzenia od kamery.")
        
    # Skróty zgodne z proponowanym API
    def take_photo(self):
        if self.camera:
            self.camera.take_photo()

    def close(self):
        """Bezpiecznie zamyka wszystkie wątki i zwialnia gniazda."""
        if self.gimbal:
            self.gimbal.close()
        if self.zoom:
            self.zoom.close()
        if self._transport:
            self._transport.close()
        self._transport = None
        self.gimbal = None
        self.zoom = None
        self.camera = None
        print("[SkydroidCamera] Zakończono.")


if __name__ == "__main__":
    print("To biblioteka sterowania Skydroid. Przykład wykonujący ruchy, zoom i zdjęcie:\n"
          "  python3 test_lepszy.py")
