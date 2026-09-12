import requests
import datetime
import time
import hmac
import hashlib
import urllib.parse
import logging
from threading import Lock

_LOGGER = logging.getLogger(__name__)


def _truncate(text, limit=200):
    """Limita la longitud de un cuerpo de respuesta antes de loguearlo (D2).

    Evita que un cuerpo de error inesperado del backend (p. ej. si alguna
    vez refleja parte de la petición) filtre más de lo necesario en los logs.
    """
    text = str(text) if text is not None else ""
    return text if len(text) <= limit else text[:limit] + "…(truncado)"


class MySairAuthError(Exception):
    """Credenciales o refresh_token inválidos/expirados: requiere reautenticación."""


class MySairConnectionError(Exception):
    """Fallo de red o del backend, no relacionado con las credenciales."""


def _http_error(status_code, body, context):
    """Clasifica una respuesta HTTP no-2xx como error de auth o de conexión.

    Regla única para todos los endpoints, en vez de enumerar los códigos que
    "se supone" que usa el backend. El incidente del 2026-09-11 vino justo de
    eso: MySair corre sobre Laravel Passport, que responde **404** (no 401)
    cuando el refresh_token ya no existe en servidor, con el cuerpo
    ``No query results for model [Laravel\\Passport\\RefreshToken]``. Al
    clasificarse como error de conexión acababa en ``ConfigEntryNotReady`` y
    Home Assistant reintentaba en bucle sin ofrecer nunca el reauth.

    - 5xx y 429: el backend está caído o nos limita → reintentar tiene sentido.
    - Cualquier otro no-2xx (400, 401, 403, 404, …): las credenciales no
      sirven → hay que preguntar al usuario.

    Devuelve la excepción ya construida (el llamante hace ``raise``).
    """
    detail = f"{context}: {status_code} {_truncate(body)}"
    if status_code >= 500 or status_code == 429:
        _LOGGER.error(f"[MySairAPI] ❌ {detail}")
        return MySairConnectionError(detail)
    _LOGGER.error(f"[MySairAPI] ❌ Sesión inválida — {detail}")
    return MySairAuthError(detail)


def extract_order_id(response):
    """Extrae el ``orderId`` de la respuesta de ``POST /send/instruction``.

    Confirmado desde la app oficial (ver docs/protocol-findings.md §8):
    ``entity.value[0].orderId``. Devuelve ``None`` si la forma no coincide
    (respuesta inesperada) en vez de lanzar, ya que solo se usa para
    correlacionar con el ACK MQTT — no es crítico para que el comando en sí
    haya funcionado.
    """
    if not isinstance(response, dict):
        return None
    try:
        return response["entity"]["value"][0].get("orderId")
    except (KeyError, IndexError, TypeError, AttributeError):
        return None


class MySairAPI:
    """Cliente API para Mysair."""

    # Expuesta como atributo de clase para que los consumidores que reciben una
    # instancia de api (p. ej. MySairMQTTClient) puedan distinguir un fallo de
    # sesión sin importar este módulo: `mqtt_handler` se importa como módulo de
    # nivel superior en los tests P0/P1 y por eso no puede usar imports
    # relativos (ver tests/conftest.py).
    AuthError = MySairAuthError

    def __init__(
        self,
        email: str,
        password: "str | None" = None,
        session: "requests.Session | None" = None,
        on_tokens_refreshed=None,
    ):
        self.email = email
        self.password = password
        self.base_url = "https://api.mysair.es/v1"
        self.access_token = None
        self.refresh_token_value = None  # evitar conflicto con método
        self.entity = None
        self.aws_credentials = None
        self.lock = Lock()
        # Sesión inyectable: facilita el mockeo en tests (ver docs/testing-strategy.md).
        self.session = session or requests.Session()
        # Callback opcional (access_token, refresh_token) -> None, invocado tras
        # login()/refresh_tokens(). El refresh_token rota en cada renovación, así
        # que el llamador (p. ej. __init__.py) debe persistir el nuevo valor.
        self.on_tokens_refreshed = on_tokens_refreshed

    def _notify_tokens(self):
        if self.on_tokens_refreshed:
            try:
                self.on_tokens_refreshed(self.access_token, self.refresh_token_value)
            except Exception:
                _LOGGER.exception("[MySairAPI] ⚠️ Error notificando refresco de tokens")

    # ==========================================================
    # 🔐 LOGIN
    # ==========================================================
    def login(self):
        """Autenticación inicial con la API Mysair (email + password).

        Lanza ``MySairAuthError`` si las credenciales son inválidas, o
        ``MySairConnectionError`` ante fallos de red o del backend.
        """
        _LOGGER.info(f"[MySairAPI] 🔐 Login {self.email}")
        try:
            resp = self.session.post(
                f"{self.base_url}/user/login",
                json={"email": self.email, "password": self.password},
                timeout=15,
            )
        except requests.RequestException as e:
            _LOGGER.error(f"[MySairAPI] ❌ Login failed: {e}")
            raise MySairConnectionError(f"Error de red en login: {e}") from e

        if resp.status_code != 200:
            raise _http_error(resp.status_code, resp.text, "Login error")

        data = resp.json()
        self.entity = data.get("entity", {})
        self.access_token = self.entity.get("access_token")
        self.refresh_token_value = self.entity.get("refresh_token")

        if not self.access_token:
            raise MySairAuthError("No se recibió access_token tras login")

        _LOGGER.info("[MySairAPI] ✅ Login OK")
        self._notify_tokens()
        return True

    # ==========================================================
    # 🔄 REFRESH TOKEN
    # ==========================================================
    def refresh_tokens(self):
        """Renueva el access_token y el refresh_token a partir del refresh_token actual.

        No requiere ``password`` (ver `docs/security-and-privacy.md` §3): es el
        mecanismo usado para restablecer la sesión en cada arranque sin guardar
        la contraseña en claro. Lanza ``MySairAuthError`` si no hay
        refresh_token o es inválido/ha expirado (requiere reautenticación), o
        ``MySairConnectionError`` ante fallos de red o del backend.
        """
        if not self.refresh_token_value:
            raise MySairAuthError("No hay refresh_token disponible.")

        _LOGGER.debug("[MySairAPI] 🔄 Renovando tokens de sesión...")
        try:
            resp = self.session.put(
                f"{self.base_url}/user/refreshtokens",
                json={"refresh_token": self.refresh_token_value},
                timeout=10,
            )
        except requests.RequestException as e:
            _LOGGER.error(f"[MySairAPI] ❌ Error al refrescar tokens: {e}")
            raise MySairConnectionError(f"Error de red al refrescar tokens: {e}") from e

        if resp.status_code != 200:
            raise _http_error(resp.status_code, resp.text, "Refresh tokens error")

        data = resp.json()
        entity = data.get("entity", {})
        self.access_token = entity.get("access_token")
        self.refresh_token_value = entity.get("refresh_token")

        if not self.access_token:
            raise MySairAuthError("No se recibió access_token al refrescar tokens")

        _LOGGER.info("[MySairAPI] ✅ Tokens renovados correctamente.")
        self._notify_tokens()
        return True

    # ==========================================================
    # 🌐 PETICIÓN AUTENTICADA (base de los endpoints de datos)
    # ==========================================================
    def _authed_request(self, method, path, context, timeout=10):
        """Hace una petición con ``Authorization: Bearer`` y clasifica los errores.

        Concentra lo que antes repetía cada endpoint: la cabecera, el timeout,
        el reintento único tras ``refresh_tokens()`` ante un 401 (mismo patrón
        que ``send_instruction``) y la clasificación de ``_http_error``.

        Lanza ``MySairAuthError`` si la sesión no sirve (el llamante debe
        acabar pidiendo reauth) o ``MySairConnectionError`` ante fallos de red
        o del backend. Devuelve el objeto ``Response``.
        """

        def _do():
            return self.session.request(
                method,
                f"{self.base_url}/{path}",
                headers={"Authorization": f"Bearer {self.access_token}"},
                timeout=timeout,
            )

        try:
            resp = _do()
            # El access_token caduca mucho antes que el refresh_token: un 401
            # aislado casi siempre se arregla renovando la sesión y repitiendo.
            # Si refresh_tokens() falla, propaga su propio error ya clasificado.
            if resp.status_code == 401:
                _LOGGER.debug(
                    f"[MySairAPI] ⚠️ Token expirado en {path}, renovando sesión y reintentando..."
                )
                self.refresh_tokens()
                resp = _do()
        except requests.RequestException as e:
            _LOGGER.error(f"[MySairAPI] ❌ Error de red en {context}: {e}")
            raise MySairConnectionError(f"Error de red en {context}: {e}") from e

        if resp.status_code != 200:
            raise _http_error(resp.status_code, resp.text, context)

        return resp

    def _authed_get_entity(self, path, context):
        """``GET`` autenticado que devuelve el campo ``entity`` de la respuesta.

        Forma común de los endpoints de descubrimiento. Una lista vacía aquí
        significa "la cuenta no tiene nada", nunca "falló la petición": los
        fallos se propagan como excepción (antes se devolvía ``[]`` en ambos
        casos, y por eso un token muerto acababa en un bucle de reintentos en
        vez de en el flujo de reauth).
        """
        return self._authed_request("GET", path, context).json().get("entity", [])

    # ==========================================================
    # ☁️ AWS CREDENTIALS
    # ==========================================================
    def refresh_aws_credentials(self):
        """Obtiene credenciales temporales de AWS IoT.

        Lanza ``MySairAuthError`` si la sesión ya no sirve: es el hilo MQTT
        quien la llama en cada (re)conexión, así que es el punto donde se
        detecta que la sesión ha muerto con la integración ya arrancada.
        """
        try:
            _LOGGER.debug("[MySairAPI] ☁️ Solicitando credenciales AWS MQTT...")
            resp = self._authed_request(
                "PUT",
                "user/refreshawscredentials",
                "AWS credentials error",
                timeout=15,
            )

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

            # Normalizar nombres para mqtt_handler.
            # aws_base_topic y aws_expires_at son opcionales (pueden no venir en
            # APIs antiguas); se usan para el topic dinámico y el refresco proactivo.
            self.aws_credentials = {
                "aws_mqtt_host": entity["aws_mqtt_host"],
                "aws_default_region": entity["aws_default_region"],
                "aws_access_key_id": entity["aws_access_key_id"],
                "aws_secret_access_key": entity["aws_secret_access_key"],
                "aws_security_token": entity["aws_security_token"],
                "aws_mqtt_user": entity["aws_mqtt_user"],
                "aws_base_topic": entity.get("aws_base_topic"),
                "aws_expires_at": entity.get("aws_expires_at"),
            }

            _LOGGER.debug(
                f"[MySairAPI] ✅ Credenciales AWS obtenidas para usuario {entity['aws_mqtt_user']}"
            )
            return self.aws_credentials

        except Exception as e:
            _LOGGER.error(f"[MySairAPI] ❌ Error al obtener credenciales AWS: {e}")
            raise

    def aws_credentials_expired(self, margin_seconds=60):
        """Indica si conviene refrescar las credenciales AWS antes de (re)conectar.

        Devuelve True si faltan credenciales o si expiran en menos de
        ``margin_seconds``. Usa ``aws_expires_at`` (unix s) cuando está presente;
        si no hay información de expiración, no fuerza refresco por tiempo.
        Confirmado desde la app oficial (ver docs/protocol-findings.md).
        """
        if not self.aws_credentials:
            return True
        expires_at = self.aws_credentials.get("aws_expires_at")
        if not expires_at:
            return False
        try:
            return time.time() >= float(expires_at) - margin_seconds
        except (TypeError, ValueError):
            return False

    def seconds_until_aws_credentials_expire(self, margin_seconds=60):
        """Segundos hasta que conviene refrescar la conexión MQTT proactivamente.

        Devuelve ``None`` si no hay credenciales o no se conoce ``aws_expires_at``
        (no se puede programar un refresco por tiempo). Si ya ha expirado o está
        dentro del margen, devuelve ``0`` (refrescar ya). Ver
        docs/protocol-findings.md §6b: la app oficial programa un
        ``setTimeout(refreshAwsCredentials, getMqttExpirationTime())`` para
        refrescar la sesión MQTT *antes* de que AWS la corte, en vez de esperar
        a que se caiga sola.
        """
        if not self.aws_credentials:
            return None
        expires_at = self.aws_credentials.get("aws_expires_at")
        if not expires_at:
            return None
        try:
            return max(float(expires_at) - time.time() - margin_seconds, 0)
        except (TypeError, ValueError):
            return None

    # ==========================================================
    # 📍 LOCATIONS / INSTALLATIONS / DEVICES
    # ==========================================================
    def get_locations(self):
        """Devuelve la lista de ubicaciones (locations)."""
        _LOGGER.info("[MySairAPI] 📍 Locations...")
        return self._authed_get_entity("locations", "Locations error")

    def get_installations(self, location_id):
        """Devuelve instalaciones (installations) de una ubicación."""
        _LOGGER.info(f"[MySairAPI] 🔧 Installations loc={location_id}")
        return self._authed_get_entity(
            f"installations?location_id={location_id}&validated=1",
            "Installations error",
        )

    def get_devices(self, installation_ref):
        """Devuelve los dispositivos (termostatos) de una instalación."""
        _LOGGER.info(f"[MySairAPI] 📟 Devices ref={installation_ref}")
        return self._authed_get_entity(
            f"devices?installation_ref={installation_ref}", "Devices error"
        )

    # ==========================================================
    # 📡 SEND INSTRUCTION (para solicitar estado o comandos)
    # ==========================================================
    def send_instruction(self, instruction):
        """Envía una instrucción directamente al endpoint /send/instruction.
        Si el token ha expirado, renueva automáticamente los tokens y credenciales AWS y reintenta una vez.
        """
        try:
            _LOGGER.debug(f"[MySairAPI] 📤 Enviando instrucción: {instruction}")
            headers = {"Authorization": f"Bearer {self.access_token}"}

            resp = self.session.post(
                f"{self.base_url}/send/instruction",
                headers=headers,
                json=instruction,
                timeout=10,
            )

            # --- Si el token expiró, refrescamos y reintentamos una vez ---
            # refresh_tokens() lanza MySairAuthError/MySairConnectionError si
            # falla; se propaga tal cual (capturado más abajo como Exception).
            if resp.status_code == 401:
                _LOGGER.debug("[MySairAPI] ⚠️ Token HTTP expirado, renovando sesión...")
                self.refresh_tokens()
                _LOGGER.debug(
                    "[MySairAPI] 🔄 Token HTTP renovado, actualizando credenciales AWS..."
                )
                self.refresh_aws_credentials()
                headers = {"Authorization": f"Bearer {self.access_token}"}
                resp = self.session.post(
                    f"{self.base_url}/send/instruction",
                    headers=headers,
                    json=instruction,
                    timeout=10,
                )

            # --- Validación final ---
            # Clasificado como el resto de endpoints: un fallo de sesión aquí
            # debe llegar como MySairAuthError para que el llamante
            # (tarea periódica / entidades) pueda pedir reauth.
            if resp.status_code != 201:
                raise _http_error(resp.status_code, resp.text, "Instruction error")

            data = resp.json()
            msg = data.get("msg", "")
            error = data.get("error", [])
            if msg != "Creado" or error:
                raise Exception(f"Instruction rejected: {_truncate(data)}")

            _LOGGER.debug("[MySairAPI] ✅ Instrucción enviada correctamente")
            return data

        except Exception as e:
            _LOGGER.error(f"[MySairAPI] ❌ Error al enviar instrucción: {e}")
            raise

    # ==========================================================
    # ⚙️ ZONE COMMAND HELPERS (para Climate, Switch, etc.)
    # ==========================================================
    def send_zone_command(
        self, ctl, device, command_type, value=None, temperature=None
    ):
        """
        Envía una instrucción formateada correctamente para controlar un termostato.

        command_type puede ser:
            - "mode"     → enciende en calor o frío (value = "0" o "1")
            - "temp"     → cambia temperatura (value = temperatura)
            - "power"    → apaga (value = "0")
            - "fanspeed" → velocidad de ventilador (value = "0".."4"; ver docs/protocol-findings.md §9)
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
                    raise ValueError(
                        "Modo inválido: usa '0' para calor o '1' para frío."
                    )
                payload_value = {"mode": value, "temperature": str(temperature or 22.0)}

            elif command_type == "temp":
                payload_value = str(value)

            elif command_type == "power":
                payload_value = "0"

            elif command_type == "fanspeed":
                if value not in ("0", "1", "2", "3", "4"):
                    raise ValueError("Velocidad de ventilador inválida: usa '0'..'4'.")
                payload_value = str(value)

            else:
                raise ValueError(f"Tipo de comando no soportado: {command_type}")

            instruction = [
                {
                    "sender": "WEB",
                    "ctl": ctl,
                    "app": app_name,
                    "device": device,
                    "command": command_type,
                    "value": payload_value,
                }
            ]

            _LOGGER.debug(
                f"[MySairAPI] ⚙️ Enviando comando '{command_type}' a {device} ({ctl}) → {instruction}"
            )
            return self.send_instruction(instruction)

        except Exception as e:
            _LOGGER.error(
                f"[MySairAPI] ❌ Error al enviar comando {command_type} para {device}: {e}"
            )
            raise

    def send_installation_command(self, ctl, command_type, value=None):
        """Envía una instrucción a nivel de instalación completa (``device`` vacío).

        command_type puede ser:
            - "stop"   → detiene la instalación completa (value = "1", F5)
            - "status" → solicita sincronización de estado (value = "sync")
        """
        try:
            if not ctl:
                raise ValueError("Falta el parámetro obligatorio 'ctl'.")

            app_name = (
                self.aws_credentials.get("aws_mqtt_user", "web0077")
                if self.aws_credentials
                else "web0077"
            )

            if command_type == "stop":
                payload_value = "1"
            elif command_type == "status":
                payload_value = "sync"
            else:
                raise ValueError(
                    f"Tipo de comando de instalación no soportado: {command_type}"
                )

            instruction = [
                {
                    "sender": "WEB",
                    "ctl": ctl,
                    "app": app_name,
                    "device": "",
                    "command": command_type,
                    "value": payload_value,
                }
            ]

            _LOGGER.debug(
                f"[MySairAPI] 🏠 Enviando comando de instalación '{command_type}' a {ctl} → {instruction}"
            )
            return self.send_instruction(instruction)

        except Exception as e:
            _LOGGER.error(
                f"[MySairAPI] ❌ Error al enviar comando de instalación {command_type} para {ctl}: {e}"
            )
            raise

    # ==========================================================
    # 🔏 FIRMAR URL AWS (WebSocket MQTT)
    # ==========================================================
    @staticmethod
    def aws_sign_url(host, region, access_key, secret_key, token):
        """Genera una URL firmada para conexión MQTT AWS."""
        service = "iotdevicegateway"
        algorithm = "AWS4-HMAC-SHA256"
        t = datetime.datetime.now(datetime.timezone.utc)
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
        signature = hmac.new(
            k_signing, string_to_sign.encode("utf-8"), hashlib.sha256
        ).hexdigest()

        canonical_querystring += f"&X-Amz-Signature={signature}"
        canonical_querystring += "&" + urllib.parse.urlencode(
            {"X-Amz-Security-Token": token}
        )

        url = f"wss://{host}/mqtt?{canonical_querystring}"
        _LOGGER.info(f"[MySairAPI] 🔗 URL MQTT firmada generada para {host}")
        return url
