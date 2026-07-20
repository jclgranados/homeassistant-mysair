import time
import json
import hmac
import hashlib
import struct
import secrets
import datetime
import logging
import threading
import websocket
import urllib.parse

_LOGGER = logging.getLogger(__name__)


def log(msg, level="info"):
    """Logger con timestamp legible."""
    now = datetime.datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
    getattr(_LOGGER, level.lower())(f"{now} {msg}")


# ==========================================================
# 🔧 Utilidades MQTT (idénticas al script funcional)
# ==========================================================
def encode_varint(x):
    encoded = b""
    while True:
        byte = x % 128
        x //= 128
        if x > 0:
            byte |= 0x80
        encoded += bytes([byte])
        if x == 0:
            break
    return encoded


def build_mqtt_connect(client_id, username, password):
    """Construye el paquete CONNECT MQTT."""
    protocol_name = b"\x00\x04MQTT"
    protocol_level = b"\x04"
    connect_flags = b"\xC2"  # CleanSession + Username + Password
    keep_alive = struct.pack("!H", 60)

    payload = (
        struct.pack("!H", len(client_id)) + client_id.encode("utf-8") +
        struct.pack("!H", len(username)) + username.encode("utf-8") +
        struct.pack("!H", len(password)) + password.encode("utf-8")
    )

    variable_header = protocol_name + protocol_level + connect_flags + keep_alive
    remaining_length = len(variable_header) + len(payload)
    fixed_header = b"\x10" + encode_varint(remaining_length)
    return fixed_header + variable_header + payload


def build_mqtt_subscribe(packet_id, topic):
    """Construye el paquete SUBSCRIBE MQTT."""
    variable_header = struct.pack("!H", packet_id)
    topic_bytes = topic.encode("utf-8")
    payload = struct.pack("!H", len(topic_bytes)) + topic_bytes + b"\x00"
    remaining_length = len(variable_header) + len(payload)
    fixed_header = b"\x82" + encode_varint(remaining_length)
    return fixed_header + variable_header + payload


def build_client_id(access_key):
    """clientId MQTT único por conexión, siguiendo el patrón de la app oficial.

    La app usa ``mqtt-client_<accessKey>_<Date.now()>``. Añadimos un sufijo
    aleatorio para garantizar unicidad aunque dos intentos caigan en el mismo
    milisegundo. Evita colisiones con la app u otras conexiones que usen el
    mismo aws_mqtt_user (AWS IoT expulsa clientIds duplicados). Ver
    docs/protocol-findings.md §6b.
    """
    return f"mqtt-client_{access_key}_{int(time.time() * 1000)}_{secrets.token_hex(3)}"


def build_status_topic(base_topic, ref):
    """Topic de suscripción de estado para un controlador.

    Estructura confirmada: ``{aws_base_topic}get/ctl/{ref}/#`` donde
    aws_base_topic suele ser ``pro/v1/``. Si no se conoce, se usa el valor
    por defecto histórico. Ver docs/protocol-findings.md §6b.
    """
    base = base_topic or "pro/v1/"
    if not base.endswith("/"):
        base += "/"
    return f"{base}get/ctl/{ref}/#"


def build_feedback_topic(base_topic, mqtt_user):
    """Topic de confirmación (ACK) de instrucciones enviadas por HTTP.

    Estructura confirmada desde la app oficial:
    ``{aws_base_topic}get/usr/{aws_mqtt_user}/feedback``, con payload
    ``{orderId, ctl, ...}`` (ver docs/protocol-findings.md §8 y
    docs/known-unknowns.md #23 — forma exacta sin confirmar con captura real).
    """
    base = base_topic or "pro/v1/"
    if not base.endswith("/"):
        base += "/"
    return f"{base}get/usr/{mqtt_user}/feedback"


# ==========================================================
# 🌐 Cliente principal MySair MQTT
# ==========================================================
class MySairMQTTClient:
    """Gestor MQTT para MySair mediante WebSocket directo."""

    def __init__(self, api, installation_refs, message_callback):
        self.api = api
        self.installation_refs = installation_refs
        self.message_callback = message_callback
        self.stop_event = threading.Event()
        self._thread = None
        self._reconnect_delay = 10
        self.ws = None
        self.connected = False
        self._base_topic = None  # aws_base_topic, se fija al conectar
        self._mqtt_user = None  # aws_mqtt_user, para el topic de feedback
        self._credential_refresh_timer = None
        self._planned_reconnect = False

    # ----------------------------------------------------------
    # 🔗 Conexión principal
    # ----------------------------------------------------------
    def start(self):
        """Inicia el cliente MQTT en un hilo separado."""
        log("🚀 [MySair MQTT] Iniciando hilo WebSocket MQTT...")
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        """Cierra la conexión WebSocket limpiamente."""
        log("🛑 [MySair MQTT] Deteniendo cliente WebSocket MQTT...")
        self.stop_event.set()
        self._cancel_credential_refresh_timer()
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass
        self.connected = False
        log("✅ [MySair MQTT] Cliente detenido.")

    # ----------------------------------------------------------
    # 🔄 Refresco proactivo de credenciales (evita que AWS corte primero)
    # ----------------------------------------------------------
    def _cancel_credential_refresh_timer(self):
        if self._credential_refresh_timer:
            self._credential_refresh_timer.cancel()
            self._credential_refresh_timer = None

    def _schedule_credential_refresh_timer(self):
        """Programa un refresco de conexión antes de que caduquen las
        credenciales AWS actuales, en vez de esperar a que AWS IoT corte la
        conexión por su cuenta (causa confirmada de desconexiones periódicas
        "sistemáticas" — ver docs/known-unknowns.md y protocol-findings.md §6b:
        la app oficial hace exactamente esto con un setTimeout).
        """
        self._cancel_credential_refresh_timer()
        delay = self.api.seconds_until_aws_credentials_expire()
        if delay is None:
            return
        self._credential_refresh_timer = threading.Timer(delay, self._on_credential_refresh_due)
        self._credential_refresh_timer.daemon = True
        self._credential_refresh_timer.start()
        log(f"⏳ [MySair MQTT] Refresco proactivo de conexión programado en {delay:.0f}s")

    def _on_credential_refresh_due(self):
        """Fuerza una reconexión con credenciales frescas antes de que caduquen."""
        log("🔄 [MySair MQTT] Refrescando conexión antes de que caduquen las credenciales AWS...")
        self._planned_reconnect = True
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass

    # ----------------------------------------------------------
    # 🧠 Lógica de conexión
    # ----------------------------------------------------------
    def _run(self):
        while not self.stop_event.is_set():
            try:
                # Refrescar credenciales AWS si faltan o están por expirar
                # (aws_expires_at). Se hace en CADA intento de conexión para no
                # reutilizar una firma caducada tras una desconexión larga.
                if self.api.aws_credentials_expired():
                    self.api.refresh_aws_credentials()

                aws = self.api.aws_credentials
                if not aws:
                    log("❌ [MySair MQTT] No se pudieron obtener credenciales AWS.", "error")
                    time.sleep(self._reconnect_delay)
                    continue

                # Datos AWS / MQTT
                host = aws.get("endpoint") or aws.get("aws_mqtt_host")
                region = aws.get("region") or aws.get("aws_default_region")
                access_key = aws.get("accessKeyId") or aws.get("aws_access_key_id")
                secret_key = aws.get("secretAccessKey") or aws.get("aws_secret_access_key")
                token = aws.get("sessionToken") or aws.get("aws_security_token")
                # clientId único por conexión (no aws_mqtt_user) para evitar
                # expulsiones mutuas con la app oficial. Ver docs/protocol-findings.md.
                client_id = build_client_id(access_key)
                username = aws.get("aws_mqtt_user")
                password = aws.get("aws_security_token")
                self._base_topic = aws.get("aws_base_topic")
                self._mqtt_user = username

                # Generar URL firmada (no se loguea: contiene la firma AWS)
                signed_url = self.api.aws_sign_url(host, region, access_key, secret_key, token)
                log(f"🔗 [MySair MQTT] Conectando a {host} como {client_id}")

                # Configurar cliente WebSocket
                headers = {"Sec-WebSocket-Protocol": "mqtt"}
                self.ws = websocket.WebSocketApp(
                    signed_url,
                    header=headers,
                    on_open=lambda ws: self._on_open(ws, client_id, username, password),
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )

                # Refrescar la conexión antes de que caduquen estas credenciales,
                # en vez de esperar a que AWS IoT la corte (ver
                # docs/known-unknowns.md — causa de desconexiones periódicas).
                self._schedule_credential_refresh_timer()

                self.ws.run_forever(ping_interval=30, ping_timeout=10)

            except Exception as e:
                log(f"❌ [MySair MQTT] Error en conexión WebSocket: {e}", "error")

            # Esperar antes de reintentar, salvo que sea un refresco
            # proactivo planificado (credenciales ya frescas: reconectar ya).
            if not self.stop_event.is_set():
                if self._planned_reconnect:
                    log("🔁 [MySair MQTT] Reconectando de inmediato (refresco proactivo de credenciales)...")
                    self._planned_reconnect = False
                else:
                    log("🔁 [MySair MQTT] Reintentando conexión en 10 segundos...")
                    time.sleep(self._reconnect_delay)

    # ----------------------------------------------------------
    # 📡 Callbacks WebSocket
    # ----------------------------------------------------------
    def _on_open(self, ws, client_id, username, password):
        """Evento: WebSocket abierto."""
        try:
            log("✅ [MySair MQTT] WebSocket abierto, enviando paquete CONNECT...")
            pkt = build_mqtt_connect(client_id, username, password)
            ws.send(pkt, opcode=websocket.ABNF.OPCODE_BINARY)
            log("📤 [MySair MQTT] CONNECT enviado.")
        except Exception as e:
            log(f"❌ [MySair MQTT] Error enviando CONNECT: {e}", "error")

    def _on_message(self, ws, message):
        """Evento: mensaje recibido desde el broker."""
        try:
            # CONNACK
            if message.startswith(b"\x20"):
                log("✅ [MySair MQTT] CONNACK recibido, suscribiendo a topics...")
                self.connected = True
                packet_id = 1
                for ref in self.installation_refs:
                    topic = build_status_topic(self._base_topic, ref)
                    pkt = build_mqtt_subscribe(packet_id, topic)
                    ws.send(pkt, opcode=websocket.ABNF.OPCODE_BINARY)
                    log(f"📡 [MySair MQTT] SUBSCRIBE enviado a: {topic}")
                    packet_id += 1

                # Confirmación (ACK) de instrucciones enviadas por HTTP, ver
                # docs/protocol-findings.md §8.
                if self._mqtt_user:
                    feedback_topic = build_feedback_topic(self._base_topic, self._mqtt_user)
                    pkt = build_mqtt_subscribe(packet_id, feedback_topic)
                    ws.send(pkt, opcode=websocket.ABNF.OPCODE_BINARY)
                    log(f"📡 [MySair MQTT] SUBSCRIBE enviado a: {feedback_topic}")
                return

            # SUBACK
            if message.startswith(b"\x90"):
                log("✅ [MySair MQTT] SUBACK recibido.")
                return

            # Mensaje de tipo PUBLISH
            if message.startswith(b"\x30"):
                try:
                    payload = message.split(b"\x00", 2)[-1]
                    decoded = payload.decode("utf-8", errors="ignore").strip()
                    log(f"📥 [MySair MQTT] Mensaje MQTT recibido: {decoded[:200]}...")

                    # 🩹 Extraer solo la parte JSON
                    start = decoded.find("{")
                    end = decoded.rfind("}") + 1
                    if start == -1 or end == 0:
                        raise ValueError("No se encontró JSON válido en el mensaje recibido.")

                    json_part = decoded[start:end]
                    data = json.loads(json_part)

                    # Extraer el topic del prefijo. Confirmado en producción
                    # (2026-07-20) que el broker no siempre envuelve el topic
                    # entre paréntesis: a veces es "(topic){json}", a veces
                    # "topic{json}" sin paréntesis (p. ej. el topic de
                    # feedback). Antes solo se reconocía la forma con
                    # paréntesis, dejando el resto como "unknown" — rompía
                    # por completo la confirmación de comandos vía feedback.
                    topic = decoded[:start].strip(" ()") if start > 0 else "unknown"

                    if self.message_callback:
                        self.message_callback({"topic": topic, "payload": data})

                except Exception as e:
                    log(f"⚠️ [MySair MQTT] Error procesando mensaje: {e}", "warning")
        except Exception as e:
            log(f"⚠️ [MySair MQTT] Error general en _on_message: {e}", "warning")

    def _on_error(self, ws, error):
        log(f"❌ [MySair MQTT] Error WebSocket: {error}", "error")

    def _on_close(self, ws, close_status_code, close_msg):
        log(f"🔌 [MySair MQTT] Conexión cerrada (code={close_status_code}, msg={close_msg})")
        self.connected = False

