#!/usr/bin/env python3
from flask import Flask, render_template_string, request, jsonify, Response, send_from_directory
import RPi.GPIO as GPIO
import time
import threading
import cv2
import os
import sys
import signal
import atexit
import logging
from datetime import datetime

# Logging konfigurieren für Service-Betrieb
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('/var/log/pin-bruteforce.log')
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# GPIO Warnungen deaktivieren und Setup optimieren
GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)
LED_PIN = 21

# Signal Handler für sauberes Beenden
def signal_handler(signum, frame):
    logger.info(f"Signal {signum} empfangen - beende Anwendung...")
    cleanup()
    sys.exit(0)

signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

# Nur setup wenn noch nicht initialisiert
try:
    GPIO.setup(LED_PIN, GPIO.OUT)
    logger.info("GPIO erfolgreich initialisiert")
except Exception as e:
    logger.error(f"GPIO Setup Fehler: {e}")

# Arbeitsverzeichnis setzen
script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)

# Ordner vorbereiten
image_dir = os.path.join(script_dir, "images")
video_dir = os.path.join(script_dir, "videos")
os.makedirs(image_dir, exist_ok=True)
os.makedirs(video_dir, exist_ok=True)

# Globale Zustände
running = False
last_pin = None
camera = None

# Kamera sicher initialisieren
def init_camera():
    global camera
    try:
        camera = cv2.VideoCapture(0)
        if camera.isOpened():
            camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            logger.info("Kamera erfolgreich initialisiert")
            return True
        else:
            logger.warning("Kamera konnte nicht geöffnet werden")
            return False
    except Exception as e:
        logger.error(f"Kamera-Initialisierung fehlgeschlagen: {e}")
        return False

# Cleanup-Funktion für sauberes Beenden
def cleanup():
    global running, camera
    logger.info("Cleanup wird ausgeführt...")
    running = False
    if camera:
        camera.release()
        logger.info("Kamera freigegeben")
    try:
        GPIO.output(LED_PIN, GPIO.LOW)
        GPIO.cleanup()
        logger.info("GPIO cleanup abgeschlossen")
    except:
        pass

# Cleanup beim Programmende registrieren
atexit.register(cleanup)

# HTML Template (gleich wie vorher)
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>PIN Bruteforce Service</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        .status { background: #f0f0f0; padding: 10px; border-radius: 5px; margin: 10px 0; }
        .controls button { padding: 10px 20px; margin: 5px; font-size: 16px; }
        .start { background: #4CAF50; color: white; border: none; border-radius: 3px; }
        .stop { background: #f44336; color: white; border: none; border-radius: 3px; }
        .gallery img { height: 120px; margin: 5px; border: 1px solid #ccc; cursor: pointer; }
        .gallery img:hover { border: 2px solid #007BFF; }
        .video-container { margin: 20px 0; }
        #current_pin { font-family: monospace; font-size: 1.5em; font-weight: bold; color: #007BFF; }
        .service-info { background: #e8f5e8; padding: 10px; border-radius: 5px; margin: 10px 0; border-left: 4px solid #4CAF50; }
    </style>
    <script>
        async function fetchPin() {
            try {
                const response = await fetch('/pin');
                const data = await response.json();
                document.getElementById('current_pin').innerText = data.current_pin || '----';
            } catch (error) {
                console.error('Fehler beim Abrufen des PINs:', error);
            }
        }

        async function updateGallery() {
            try {
                const res = await fetch('/images_list');
                const data = await res.json();
                const gallery = document.getElementById('gallery');
                gallery.innerHTML = '';
                
                if (data.images.length === 0) {
                    gallery.innerHTML = '<p>Noch keine Bilder aufgenommen.</p>';
                    return;
                }
                
                data.images.forEach(img => {
                    const link = document.createElement('a');
                    link.href = '/images/' + img;
                    link.target = '_blank';
                    const image = document.createElement('img');
                    image.src = '/images/' + img;
                    image.alt = img;
                    link.appendChild(image);
                    gallery.appendChild(link);
                });
            } catch (error) {
                console.error('Fehler beim Aktualisieren der Galerie:', error);
            }
        }

        setInterval(fetchPin, 2000);
        setInterval(updateGallery, 3000);
        window.onload = () => {
            fetchPin();
            updateGallery();
        };
    </script>
</head>
<body>
    <h1>🔓 PIN Bruteforce Service</h1>
    
    <div class="service-info">
        <strong>🟢 Service läuft im Hintergrund</strong><br>
        Dieses Interface ist permanent verfügbar und startet automatisch beim Systemstart.
    </div>
    
    <div class="controls">
        <form method="POST">
            <button name="action" value="start" type="submit" class="start">▶️ Starten</button>
            <button name="action" value="stop" type="submit" class="stop">⏹️ Stoppen</button>
        </form>
    </div>

    <div class="status">
        <p><strong>Status:</strong> {{ status or 'Bereit zum Starten...' }}</p>
        <p><strong>Aktueller PIN:</strong> <span id="current_pin">----</span></p>
    </div>

    <div class="video-container">
        <h2>📹 Live-Vorschau</h2>
        <img src="/video_feed" width="480" alt="Live Video Feed">
    </div>

    <h2>📷 Aufgenommene Bilder</h2>
    <div id="gallery" class="gallery"></div>
</body>
</html>
"""

def send_light_pulse():
    """Einzelnen kurzen Lichtimpuls senden"""
    GPIO.output(LED_PIN, GPIO.HIGH)
    time.sleep(0.2)
    GPIO.output(LED_PIN, GPIO.LOW)
    time.sleep(0.3)

def send_pin(pin_str):
    """PIN gemäß mME-Anleitung eingeben"""
    logger.info(f"🔓 Starte PIN-Eingabe für: {pin_str}")
    
    # Ersten Impuls senden um PIN-Eingabe zu starten
    send_light_pulse()
    time.sleep(1)
    
    for i, digit_char in enumerate(pin_str):
        target_digit = int(digit_char)
        logger.info(f"  Ziffer {i+1}: {target_digit}")
        
        # Von 0 auf Zielziffer hochzählen durch kurze Lichtimpulse
        for pulse_count in range(target_digit):
            send_light_pulse()
            time.sleep(0.1)
        
        # 3 Sekunden warten für nächste Ziffer (außer nach der letzten)
        if i < 3:
            logger.info(f"  Warte 3s für nächste Ziffer...")
            time.sleep(3.1)
    
    logger.info("✅ PIN-Eingabe abgeschlossen")

def record_images_and_video():
    """Bilder und Video während des Bruteforce aufnehmen"""
    if not camera:
        logger.error("❌ Kamera nicht verfügbar!")
        return
        
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    video_path = os.path.join(video_dir, f"session_{timestamp}.avi")
    fourcc = cv2.VideoWriter_fourcc(*'XVID')
    out = cv2.VideoWriter(video_path, fourcc, 10.0, (640, 480))
    img_count = 1
    logger.info(f"📹 Videoaufnahme gestartet: {video_path}")

    while running:
        ret, frame = camera.read()
        if ret:
            # Zeitstempel zum Bild hinzufügen
            timestamp_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            cv2.putText(frame, f"PIN: {last_pin or '----'} | {timestamp_str}", 
                       (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            
            # Speichere Bild
            img_file = os.path.join(image_dir, f"{timestamp}_{img_count:04d}.jpg")
            cv2.imwrite(img_file, frame)
            
            # Schreibe ins Video
            out.write(frame)
            logger.info(f"📷 Bild gespeichert: {img_file}")
            img_count += 1
        else:
            logger.warning("⚠️ Kein Kamerabild erhalten")
        
        time.sleep(3)

    out.release()
    logger.info("🛑 Videoaufnahme beendet")

def generate_video_stream():
    """Generator für Live-Video-Stream"""
    while True:
        if not camera:
            time.sleep(1)
            continue
            
        success, frame = camera.read()
        if not success:
            time.sleep(0.1)
            continue
            
        try:
            _, buffer = cv2.imencode('.jpg', frame)
            yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
        except Exception as e:
            logger.error(f"Stream-Fehler: {e}")
            time.sleep(1)
            continue

def bruteforce_pins():
    """Hauptfunktion für PIN-Bruteforce"""
    global running, last_pin
    running = True
    
    # Aufnahme-Thread starten
    record_thread = threading.Thread(target=record_images_and_video)
    record_thread.daemon = True
    record_thread.start()
    
    try:
        logger.info("🚀 Bruteforce gestartet...")
        for i in range(0, 10000):
            if not running:
                logger.info("🛑 Bruteforce gestoppt durch Benutzer")
                break
                
            pin = f"{i:04d}"
            last_pin = pin
            logger.info(f"➡️ Teste PIN: {pin}")
            
            send_pin(pin)
            time.sleep(3)
            
    except Exception as e:
        logger.error(f"❌ Fehler im Bruteforce: {e}")
    finally:
        running = False
        record_thread.join(timeout=5)
        GPIO.output(LED_PIN, GPIO.LOW)
        logger.info("✅ Bruteforce beendet")

@app.route('/', methods=['GET', 'POST'])
def index():
    global running
    status = None
    
    if request.method == 'POST':
        action = request.form.get("action")
        
        if action == "start" and not running:
            if not camera:
                if not init_camera():
                    status = "❌ Kamera konnte nicht initialisiert werden!"
                    logger.error(status)
                    return render_template_string(HTML_TEMPLATE, status=status)
            
            thread = threading.Thread(target=bruteforce_pins)
            thread.daemon = True
            thread.start()
            status = "✅ Bruteforce gestartet – Video & Bilderaufnahme läuft..."
            logger.info(status)
            
        elif action == "stop" and running:
            running = False
            status = "🛑 Bruteforce wird gestoppt..."
            logger.info(status)
            
    return render_template_string(HTML_TEMPLATE, status=status)

@app.route('/pin')
def get_current_pin():
    return jsonify({'current_pin': last_pin, 'running': running})

@app.route('/video_feed')
def video_feed():
    return Response(generate_video_stream(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/images/<filename>')
def image_file(filename):
    return send_from_directory(image_dir, filename)

@app.route('/images_list')
def images_list():
    try:
        files = sorted([f for f in os.listdir(image_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png'))])
        return jsonify({'images': files})
    except Exception as e:
        logger.error(f"Fehler beim Laden der Bilderliste: {e}")
        return jsonify({'images': [], 'error': str(e)})

if __name__ == '__main__':
    # Kamera beim Start initialisieren
    init_camera()
    
    logger.info("🌐 Starte PIN-Bruteforce Service...")
    logger.info("📱 Web-Interface verfügbar auf Port 5000")
    
    try:
        app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
    except KeyboardInterrupt:
        logger.info("🛑 Service wird beendet...")
    except Exception as e:
        logger.error(f"Service Fehler: {e}")
    finally:
        cleanup()
