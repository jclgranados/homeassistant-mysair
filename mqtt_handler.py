import json
import threading
import ssl
import paho.mqtt.client as mqtt


class MySairMQTTClient:
    """Cliente MQTT para conexión con AWS IoT Core (MySair)."""

    def __init__(self, aws_data, on_message_callback):
        self.aws = aws_data
        self.on_message_callback = on_message_callback
        self.client = mqtt.Client()
        self.client.username_pw_set(self.aws.get("aws_mqtt_user"), None)
        self.client.on_message = self._on_message
        self.client.on_connect = self._on_connect

    def _on_connect(self, client, userdata, flags, rc):
        """Suscripción inicial cuando se conecta al broker."""
        if rc == 0:
            print("✅ [MySair MQTT] Conectado correctamente al broker AWS IoT")
            base_topic = self.aws.get("aws_base_topic", "pro/v1/")
            ctl = self.aws.get("aws_mqtt_user", "web0000").replace("web", "MYS")
            topic = f"{base_topic}get/ctl/{ctl}/#"
            client.subscribe(topic)
            print(f"📡 [MySair MQTT] Suscrito al topic: {topic}")
        else:
            print(f"⚠️ [MySair MQTT] Error al conectar: código {rc}")

    def _on_message(self, client, userdata, msg):
        """Procesa mensajes MQTT entrantes."""
        try:
            payload = msg.payload.decode()
            data = json.loads(payload)
            print(f"📨 [MySair MQTT] Mensaje recibido en {msg.topic}")
            self.on_message_callback(data)
        except json.JSONDecodeError:
            print(f"⚠️ [MySair MQTT] No se pudo decodificar JSON: {msg.payload[:100]}")
        except Exception as e:
            print(f"❌ [MySair MQTT] Error procesando mensaje: {e}")

    def start(self):
        """Arranca el cliente MQTT en un hilo aparte (no bloquea el event loop)."""

        def _run():
            try:
                print("🔐 [MySair MQTT] Configurando TLS...")
                # Para pruebas usamos TLS sin verificación estricta
                # (AWS exige certificados firmados; implementaremos firma SigV4 más adelante)
                self.client.tls_set(cert_reqs=ssl.CERT_NONE)
                self.client.tls_insecure_set(True)

                broker = self.aws.get("aws_mqtt_host")
                print(f"🚀 [MySair MQTT] Conectando al broker {broker}:8883")
                self.client.connect(broker, 8883)

                self.client.loop_forever()

            except Exception as e:
                print(f"❌ [MySair MQTT] Error en conexión MQTT: {e}")

        threading.Thread(target=_run, daemon=True).start()

