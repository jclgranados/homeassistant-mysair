import requests
import datetime
import hmac
import hashlib
import urllib.parse
import logging
from threading import Lock

_LOGGER = logging.getLogger(__name__)


class MySairAPI:
    """Cliente API para Mysair."""

    def __init__(self, email: str, password: str):
        self.email = email
        self.password = password
        self.base_url = "https://api.mysair.es/v1"
        self.access_token = None
        self.refresh_token_value = None  # evitar conflicto con método
        self.entity = None
        self.aws_credentials = None
        self.lock = Lock()

    # ==========================================================
    # 🔐 LOGIN
    # ==========================================================
    def login(self):
        """Autenticación inicial con la API Mysair."""
        try:
            _LOGGER.info(f"[MySairAPI] 🔐 Login {self.email}")
            resp = requests.post(
                f"{self.base_url}/user/login",
                json={"email": self.email, "password": self.password},
                timeout=15,
            )

            if resp.status_code != 200:
                raise Exception(f"Login error: {resp.status_code} {resp.text}")

            data = resp.json()
            self.entity = data.get("entity", {})
            self.access_token = self.entity.get("access_token")
            self.refresh_token_value = self.entity.get("refresh_token")

            if not self.access_token:
                raise Exception("No se recibió access_token tras login")

            _LOGGER.info("[MySairAPI] ✅ Login OK")
            return True

        except Exception as e:
            _LOGGER.error(f"[MySairAPI] ❌ Login failed: {e}")
            raise

    # ==========================================================
    # 🔄 REFRESH TOKEN
    # ==========================================================
    def refresh_tokens(self):
        """Renueva el access_token y el refresh_token."""
        try:
            if not self.refresh_token_value:
                _LOGGER.warning("[MySairAPI] ⚠️ No hay refresh_token disponible.")
                return False

            _LOGGER.info("[MySairAPI] 🔄 Renovando tokens de sesión...")
            resp = requests.put(
                f"{self.base_url}/user/refreshtokens",
                json={"refresh_token": self.refresh_token_value},
                timeout=10,
            )

            if resp.status_code != 200:
                raise Exception(f"Refresh tokens error: {resp.status_code} {resp.text}")

            data = resp.json()
            entity = data.get("entity", {})
            self.access_token = entity.get("access_token")
            self.refresh_token_value = entity.get("refresh_token")

            if not self.access_token:
                raise Exception("No se recibió access_token al refrescar tokens")

            _LOGGER.info("[MySairAPI] ✅ Tokens renovados correctamente.")
            return True

        except Exception as e:
            _LOGGER.error(f"[MySairAPI] ❌ Error al refrescar tokens: {e}")
            return False

    # ==========================================================
    # ☁️ AWS CREDENTIALS
    # ==========================================================
    def refresh_aws_credentials(self):
        """Obtiene credenciales temporales de AWS IoT."""
        try:
            _LOGGER.info("[MySairAPI] ☁️ Solicitando credenciales AWS MQTT...")
            headers = {"Authorization": f"Bearer {self.access_token}"}
            resp = requests.put(f"{self.base_url}/user/refreshawscredentials", headers=headers, timeout=15)

            if resp.status_code != 200:
                raise Exception(f"AWS credentials error: {resp.status_code} {resp.text}")

            data = resp.json()
            entity = data.get("entity", {})

            required_keys = [
                "aws_mqtt_host",
                "aws_default_region",
                "aws_access_key_id",
                "aws_secret_access_key",
                "aws_security_token",
                "aws_mqtt_user",
            ]

            # Validar presencia de claves
            if not all(k in entity for k in required_keys):
                raise Exception("Credenciales AWS incompletas o inválidas")

            # Normalizar nombres para mqtt_handler
            self.aws_credentials = {
                "aws_mqtt_host": entity["aws_mqtt_host"],
                "aws_default_region": entity["aws_default_region"],
                "aws_access_key_id": entity["aws_access_key_id"],
                "aws_secret_access_key": entity["aws_secret_access_key"],
                "aws_security_token": entity["aws_security_token"],
                "aws_mqtt_user": entity["aws_mqtt_user"],
            }

            _LOGGER.info(f"[MySairAPI] ✅ Credenciales AWS obtenidas para usuario {entity['aws_mqtt_user']}")
            return self.aws_credentials

        except Exception as e:
            _LOGGER.error(f"[MySairAPI] ❌ Error al obtener credenciales AWS: {e}")
            raise

    # ==========================================================
    # 📍 LOCATIONS / INSTALLATIONS / DEVICES
    # ==========================================================
    def get_locations(self):
        """Devuelve la lista de ubicaciones (locations)."""
        try:
            _LOGGER.info("[MySairAPI] 📍 Locations...")
            headers = {"Authorization": f"Bearer {self.access_token}"}
            resp = requests.get(f"{self.base_url}/locations", headers=headers, timeout=10)

            if resp.status_code != 200:
                raise Exception(f"Locations error: {resp.status_code} {resp.text}")

            return resp.json().get("entity", [])
        except Exception as e:
            _LOGGER.error(f"[MySairAPI] ❌ Error obteniendo locations: {e}")
            return []

    def get_installations(self, location_id):
        """Devuelve instalaciones (installations) de una ubicación."""
        try:
            _LOGGER.info(f"[MySairAPI] 🔧 Installations loc={location_id}")
            headers = {"Authorization": f"Bearer {self.access_token}"}
            resp = requests.get(
                f"{self.base_url}/installations?location_id={location_id}&validated=1",
                headers=headers,
                timeout=10,
            )
            if resp.status_code != 200:
                raise Exception(f"Installations error: {resp.status_code} {resp.text}")
            return resp.json().get("entity", [])
        except Exception as e:
            _LOGGER.error(f"[MySairAPI] ❌ Error obteniendo instalaciones: {e}")
            return []

    def get_devices(self, installation_ref):
        """Devuelve los dispositivos (termostatos) de una instalación."""
        try:
            _LOGGER.info(f"[MySairAPI] 📟 Devices ref={installation_ref}")
            headers = {"Authorization": f"Bearer {self.access_token}"}
            resp = requests.get(
                f"{self.base_url}/devices?installation_ref={installation_ref}",
                headers=headers,
                timeout=10,
            )
            if resp.status_code != 200:
                raise Exception(f"Devices error: {resp.status_code} {resp.text}")
            return resp.json().get("entity", [])
        except Exception as e:
            _LOGGER.error(f"[MySairAPI] ❌ Error obteniendo devices: {e}")
            return []

    # ==========================================================
    # 📡 SEND INSTRUCTION (para solicitar estado o comandos)
    # ==========================================================
    def send_instruction(self, instruction):
        """Envía una instrucción directamente al endpoint /send/instruction.
        Si el token ha expirado, renueva automáticamente los tokens y credenciales AWS y reintenta una vez.
        """
        try:
            _LOGGER.info(f"[MySairAPI] 📤 Enviando instrucción: {instruction}")
            headers = {"Authorization": f"Bearer {self.access_token}"}

            resp = requests.post(
                f"{self.base_url}/send/instruction", headers=headers, json=instruction, timeout=10
            )

            # --- Si el token expiró, refrescamos y reintentamos una vez ---
            if resp.status_code == 401:
                _LOGGER.info("[MySairAPI] ⚠️ Token HTTP expirado, renovando sesión...")
                if self.refresh_tokens():
                    _LOGGER.info("[MySairAPI] 🔄 Token HTTP renovado, actualizando credenciales AWS...")
                    self.refresh_aws_credentials()
                    headers = {"Authorization": f"Bearer {self.access_token}"}
                    resp = requests.post(
                        f"{self.base_url}/send/instruction", headers=headers, json=instruction, timeout=10
                    )

            # --- Validación final ---
            if resp.status_code != 201:
                raise Exception(f"Instruction error: {resp.status_code} {resp.text}")

            data = resp.json()
            msg = data.get("msg", "")
            error = data.get("error", [])
            if msg != "Creado" or error:
                raise Exception(f"Instruction rejected: {data}")

            _LOGGER.info("[MySairAPI] ✅ Instrucción enviada correctamente")
            return data

        except Exception as e:
            _LOGGER.error(f"[MySairAPI] ❌ Error al enviar instrucción: {e}")
            raise


    # ==========================================================
    # ⚙️ ZONE COMMAND HELPERS (para Climate, Switch, etc.)
    # ==========================================================
    def send_zone_command(self, ctl, device, command_type, value=None, temperature=None):
        """
        Envía una instrucción formateada correctamente para controlar un termostato.

        command_type puede ser:
            - "mode"   → enciende en calor o frío (value = "0" o "1")
            - "temp"   → cambia temperatura (value = temperatura)
            - "power"  → apaga (value = "0")
        """
        try:
            if not ctl or not device:
                raise ValueError("Faltan parámetros obligatorios (ctl o device).")

            app_name = (
                self.aws_credentials.get("aws_mqtt_user", "web0077")
                if self.aws_credentials
                else "web0077"
            )

            if command_type == "mode":
                if value not in ["0", "1"]:
                    raise ValueError("Modo inválido: usa '0' para calor o '1' para frío.")
                payload_value = {"mode": value, "temperature": str(temperature or 22.0)}

            elif command_type == "temp":
                payload_value = str(value)

            elif command_type == "power":
                payload_value = "0"

            else:
                raise ValueError(f"Tipo de comando no soportado: {command_type}")

            instruction = [{
                "sender": "WEB",
                "ctl": ctl,
                "app": app_name,
                "device": device,
                "command": command_type,
                "value": payload_value
            }]

            _LOGGER.info(f"[MySairAPI] ⚙️ Enviando comando '{command_type}' a {device} ({ctl}) → {instruction}")
            return self.send_instruction(instruction)

        except Exception as e:
            _LOGGER.error(f"[MySairAPI] ❌ Error al enviar comando {command_type} para {device}: {e}")
            raise

    # ==========================================================
    # 🔏 FIRMAR URL AWS (WebSocket MQTT)
    # ==========================================================
    @staticmethod
    def aws_sign_url(host, region, access_key, secret_key, token):
        """Genera una URL firmada para conexión MQTT AWS."""
        method = "GET"
        service = "iotdevicegateway"
        algorithm = "AWS4-HMAC-SHA256"
        t = datetime.datetime.utcnow()
        amz_date = t.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = t.strftime("%Y%m%d")
        credential_scope = f"{date_stamp}/{region}/{service}/aws4_request"

        canonical_querystring = (
            f"X-Amz-Algorithm={algorithm}&"
            f"X-Amz-Credential={urllib.parse.quote_plus(access_key + '/' + credential_scope)}&"
            f"X-Amz-Date={amz_date}&"
            f"X-Amz-SignedHeaders=host"
        )

        canonical_headers = f"host:{host}\n"
        payload_hash = hashlib.sha256(b"").hexdigest()
        canonical_request = f"GET\n/mqtt\n{canonical_querystring}\n{canonical_headers}\nhost\n{payload_hash}"

        string_to_sign = (
            f"{algorithm}\n{amz_date}\n{credential_scope}\n"
            f"{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"
        )

        def sign(key, msg):
            return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

        k_date = sign(("AWS4" + secret_key).encode("utf-8"), date_stamp)
        k_region = sign(k_date, region)
        k_service = sign(k_region, service)
        k_signing = sign(k_service, "aws4_request")
        signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

        canonical_querystring += f"&X-Amz-Signature={signature}"
        canonical_querystring += "&" + urllib.parse.urlencode({"X-Amz-Security-Token": token})

        url = f"wss://{host}/mqtt?{canonical_querystring}"
        _LOGGER.info(f"[MySairAPI] 🔗 URL MQTT firmada generada para {host}")
        return url

