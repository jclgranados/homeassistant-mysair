"""Tests P0/P1 de la robustez de conexión MQTT (client_id, topic, expiración).

Sin Home Assistant. Requiere websocket-client (mqtt_handler) y requests (api).
"""

import time

import pytest

pytest.importorskip("websocket")
pytest.importorskip("requests")

import struct

import mqtt_handler
from mqtt_handler import (
    build_client_id,
    build_status_topic,
    build_feedback_topic,
    build_mqtt_subscribe,
    compute_backoff_delay,
    decode_varint,
    encode_varint,
    parse_mqtt_publish,
    MySairMQTTClient,
)
from api import MySairAPI


# --- build_client_id (#20) ---

def test_client_id_is_unique_per_call():
    a = build_client_id("AKIATEST")
    b = build_client_id("AKIATEST")
    assert a != b  # incluye timestamp en ms


def test_client_id_format():
    cid = build_client_id("AKIATEST")
    assert cid.startswith("mqtt-client_AKIATEST_")
    parts = cid.split("_")
    # mqtt-client / accessKey / timestamp(ms) / random
    assert len(parts) == 4
    assert parts[2].isdigit()  # timestamp
    assert parts[3]  # sufijo aleatorio no vacío


def test_client_id_is_not_the_mqtt_user():
    # No debe ser el aws_mqtt_user (evita expulsiones con la app oficial)
    assert build_client_id("AKIATEST") != "web0000"


# --- build_status_topic (#5) ---

def test_status_topic_with_base_topic():
    assert build_status_topic("pro/v1/", "INST_A") == "pro/v1/get/ctl/INST_A/#"


def test_status_topic_base_without_trailing_slash():
    assert build_status_topic("pro/v2", "INST_A") == "pro/v2/get/ctl/INST_A/#"


def test_status_topic_default_when_missing():
    assert build_status_topic(None, "INST_A") == "pro/v1/get/ctl/INST_A/#"
    assert build_status_topic("", "INST_A") == "pro/v1/get/ctl/INST_A/#"


# --- build_feedback_topic (#7, known-unknowns #23) ---

def test_feedback_topic_with_base_topic():
    assert build_feedback_topic("pro/v1/", "web0000") == "pro/v1/get/usr/web0000/feedback"


def test_feedback_topic_base_without_trailing_slash():
    assert build_feedback_topic("pro/v2", "web0000") == "pro/v2/get/usr/web0000/feedback"


def test_feedback_topic_default_when_missing():
    assert build_feedback_topic(None, "web0000") == "pro/v1/get/usr/web0000/feedback"


# --- aws_credentials_expired (#22) ---

def _api_with_creds(**extra):
    api = MySairAPI("e", "p")
    api.aws_credentials = {"aws_mqtt_user": "web0000", **extra}
    return api


def test_expired_when_no_credentials():
    api = MySairAPI("e", "p")
    api.aws_credentials = None
    assert api.aws_credentials_expired() is True


def test_not_expired_without_expiry_info():
    # Con credenciales pero sin aws_expires_at: no forzamos refresco por tiempo
    api = _api_with_creds()
    assert api.aws_credentials_expired() is False


def test_expired_when_past_expiry():
    api = _api_with_creds(aws_expires_at=time.time() - 10)
    assert api.aws_credentials_expired() is True


def test_expired_within_margin():
    # Expira en 30s, margen por defecto 60s → conviene refrescar
    api = _api_with_creds(aws_expires_at=time.time() + 30)
    assert api.aws_credentials_expired() is True


def test_not_expired_with_ample_time():
    api = _api_with_creds(aws_expires_at=time.time() + 3600)
    assert api.aws_credentials_expired() is False


def test_expired_ignores_bad_expiry_value():
    api = _api_with_creds(aws_expires_at="not-a-number")
    assert api.aws_credentials_expired() is False


# --- seconds_until_aws_credentials_expire (refresco proactivo de conexión) ---

def test_seconds_until_expire_none_without_credentials():
    api = MySairAPI("e", "p")
    api.aws_credentials = None
    assert api.seconds_until_aws_credentials_expire() is None


def test_seconds_until_expire_none_without_expiry_info():
    api = _api_with_creds()
    assert api.seconds_until_aws_credentials_expire() is None


def test_seconds_until_expire_computes_remaining_time():
    api = _api_with_creds(aws_expires_at=time.time() + 660)
    # 660s hasta expirar - 60s de margen = ~600s
    assert 590 <= api.seconds_until_aws_credentials_expire() <= 600


def test_seconds_until_expire_zero_when_within_margin():
    api = _api_with_creds(aws_expires_at=time.time() + 30)
    assert api.seconds_until_aws_credentials_expire() == 0


def test_seconds_until_expire_zero_when_already_past():
    api = _api_with_creds(aws_expires_at=time.time() - 100)
    assert api.seconds_until_aws_credentials_expire() == 0


def test_seconds_until_expire_ignores_bad_value():
    api = _api_with_creds(aws_expires_at="not-a-number")
    assert api.seconds_until_aws_credentials_expire() is None


# --- _on_message: extracción de topic de un frame PUBLISH ---
# Bug real de producción (2026-07-20): el broker no siempre envuelve el
# topic entre paréntesis "(topic){json}" — el topic de feedback llega como
# "topic{json}" sin paréntesis, y antes se clasificaba como "unknown",
# rompiendo la confirmación de comandos por completo.

def _publish_message(topic_plus_json: bytes) -> bytes:
    # Fixed header + 2 bytes nulos (imitando cabecera/packet id variables,
    # cuyo contenido _on_message ignora) + "topic{json...}".
    return b"\x30" + b"\x00garbage\x00" + topic_plus_json


def _client():
    received = []
    client = MySairMQTTClient(api=None, installation_refs=[], message_callback=received.append)
    return client, received


def test_on_message_extracts_topic_without_parens():
    client, received = _client()
    msg = _publish_message(b'pro/v1/get/usr/web0077/feedback{"orderId":"5b1ae0","ctl":"INST_A"}')
    client._on_message(None, msg)

    assert len(received) == 1
    assert received[0]["topic"] == "pro/v1/get/usr/web0077/feedback"
    assert received[0]["payload"] == {"orderId": "5b1ae0", "ctl": "INST_A"}


def test_on_message_extracts_topic_with_parens():
    client, received = _client()
    msg = _publish_message(b'(pro/v1/get/ctl/INST_A/status{"ctl":"INST_A","value":"{}"}')
    client._on_message(None, msg)

    assert len(received) == 1
    assert received[0]["topic"] == "pro/v1/get/ctl/INST_A/status"


def test_on_message_no_prefix_is_unknown():
    client, received = _client()
    msg = _publish_message(b'{"ctl":"INST_A"}')
    client._on_message(None, msg)

    assert len(received) == 1
    assert received[0]["topic"] == "unknown"


# --- decode_varint / parse_mqtt_publish (E1, known-unknowns #6) ---
#
# Confirmado por inferencia cruzada de capturas reales: el topic de status
# ("...status", 40 caracteres) mostraba un "(" delante en los logs porque
# chr(40) == '(' — es el byte bajo del campo de longitud MQTT estándar de
# 2 bytes que precede al Topic Name, no un envoltorio de la app. El topic de
# feedback (31 caracteres, chr(31) no imprimible) no mostraba nada visible.
# Estos tests construyen frames PUBLISH sintéticos pero conformes al
# estándar MQTT 3.1.1 para verificar el decodificador contra esa evidencia.

def _build_publish_frame(topic: str, payload: bytes, qos: int = 0, packet_id: int = 1) -> bytes:
    topic_bytes = topic.encode("utf-8")
    variable_header = struct.pack("!H", len(topic_bytes)) + topic_bytes
    if qos > 0:
        variable_header += struct.pack("!H", packet_id)
    remaining = variable_header + payload
    fixed_header_byte = 0x30 | ((qos & 0x03) << 1)
    return bytes([fixed_header_byte]) + encode_varint(len(remaining)) + remaining


def test_decode_varint_roundtrip_with_encode_varint():
    for n in (0, 1, 127, 128, 16383, 16384, 2097151):
        encoded = encode_varint(n)
        value, pos = decode_varint(encoded)
        assert value == n
        assert pos == len(encoded)


def test_decode_varint_incomplete_returns_none():
    value, pos = decode_varint(b"\x80")  # bit de continuación sin más bytes
    assert value is None
    assert pos == 0


def test_parse_mqtt_publish_status_topic_matches_real_capture_length():
    # 40 caracteres: el mismo largo que hacía aparecer un "(" fantasma en los logs.
    topic = "pro/v1/get/ctl/MYS94B97E0C9177FB6/status"
    assert len(topic) == 40
    payload = b'{"ctl":"MYS94B97E0C9177FB6","value":"{}"}'
    frame = _build_publish_frame(topic, payload, qos=0)

    parsed_topic, parsed_payload = parse_mqtt_publish(frame)

    assert parsed_topic == topic
    assert parsed_payload == payload


def test_parse_mqtt_publish_feedback_topic_matches_real_capture_length():
    # 31 caracteres: el largo que no mostraba ningún carácter fantasma visible.
    topic = "pro/v1/get/usr/web0077/feedback"
    assert len(topic) == 31
    payload = b'{"orderId":"5b1ae0","ctl":"INST_A"}'
    frame = _build_publish_frame(topic, payload, qos=0)

    parsed_topic, parsed_payload = parse_mqtt_publish(frame)

    assert parsed_topic == topic
    assert parsed_payload == payload


def test_parse_mqtt_publish_qos1_skips_packet_identifier():
    topic = "pro/v1/get/ctl/INST_A/status"
    payload = b'{"ctl":"INST_A"}'
    frame = _build_publish_frame(topic, payload, qos=1, packet_id=42)

    parsed_topic, parsed_payload = parse_mqtt_publish(frame)

    assert parsed_topic == topic
    assert parsed_payload == payload


def test_parse_mqtt_publish_rejects_non_publish_frame():
    assert parse_mqtt_publish(b"\x20\x02\x00\x00") == (None, None)  # CONNACK


def test_parse_mqtt_publish_rejects_truncated_frame():
    assert parse_mqtt_publish(b"\x30\x10\x00\x28pro/v1") == (None, None)


def test_parse_mqtt_publish_rejects_empty_message():
    assert parse_mqtt_publish(b"") == (None, None)


def test_on_message_uses_strict_parser_for_well_formed_frame():
    client, received = _client()
    topic = "pro/v1/get/usr/web0077/feedback"
    payload = b'{"orderId":"5b1ae0","ctl":"INST_A"}'
    frame = _build_publish_frame(topic, payload, qos=0)

    client._on_message(None, frame)

    assert len(received) == 1
    assert received[0]["topic"] == topic
    assert received[0]["payload"] == {"orderId": "5b1ae0", "ctl": "INST_A"}


def test_on_message_falls_back_when_strict_parse_inconclusive():
    # Mismos mensajes "a mano" que test_on_message_extracts_topic_without_parens:
    # no son un frame MQTT válido, así que deben seguir resolviéndose por la
    # heurística de texto (comportamiento sin cambios para estos casos).
    client, received = _client()
    msg = _publish_message(b'pro/v1/get/usr/web0077/feedback{"orderId":"5b1ae0","ctl":"INST_A"}')
    client._on_message(None, msg)

    assert len(received) == 1
    assert received[0]["topic"] == "pro/v1/get/usr/web0077/feedback"


# --- Refresco proactivo de conexión (evita que AWS corte primero) ---

class _FakeTimer:
    """Doble de threading.Timer: no arranca hilos reales ni espera de verdad."""

    instances = []

    def __init__(self, delay, func):
        self.delay = delay
        self.func = func
        self.started = False
        self.cancelled = False
        self.daemon = False
        _FakeTimer.instances.append(self)

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True


@pytest.fixture(autouse=True)
def _reset_fake_timers(monkeypatch):
    _FakeTimer.instances = []
    monkeypatch.setattr(mqtt_handler.threading, "Timer", _FakeTimer)
    yield


def _client_with_creds(**extra):
    api = MySairAPI("e", "p")
    api.aws_credentials = {"aws_mqtt_user": "web0000", **extra}
    return MySairMQTTClient(api=api, installation_refs=[], message_callback=lambda data: None)


def test_schedule_credential_refresh_timer_creates_timer():
    client = _client_with_creds(aws_expires_at=time.time() + 660)
    client._schedule_credential_refresh_timer()

    assert len(_FakeTimer.instances) == 1
    timer = _FakeTimer.instances[0]
    assert timer.started is True
    assert 590 <= timer.delay <= 600


def test_schedule_credential_refresh_timer_noop_without_expiry_info():
    client = _client_with_creds()  # sin aws_expires_at
    client._schedule_credential_refresh_timer()

    assert _FakeTimer.instances == []
    assert client._credential_refresh_timer is None


def test_schedule_credential_refresh_timer_cancels_previous():
    client = _client_with_creds(aws_expires_at=time.time() + 660)
    client._schedule_credential_refresh_timer()
    first_timer = _FakeTimer.instances[0]

    client._schedule_credential_refresh_timer()

    assert first_timer.cancelled is True
    assert len(_FakeTimer.instances) == 2
    assert client._credential_refresh_timer is _FakeTimer.instances[1]


def test_cancel_credential_refresh_timer_clears_state():
    client = _client_with_creds(aws_expires_at=time.time() + 660)
    client._schedule_credential_refresh_timer()
    timer = client._credential_refresh_timer

    client._cancel_credential_refresh_timer()

    assert timer.cancelled is True
    assert client._credential_refresh_timer is None


def test_on_credential_refresh_due_marks_planned_reconnect_and_closes_ws():
    client = _client_with_creds()
    closed = []
    client.ws = type("FakeWs", (), {"close": lambda self: closed.append(True)})()

    client._on_credential_refresh_due()

    assert client._planned_reconnect is True
    assert closed == [True]


# --- compute_backoff_delay (E3) ---

class _ZeroJitterRng:
    """Doble de `random`: sin aleatoriedad, para comprobar el valor exacto del backoff."""

    def uniform(self, a, b):
        return 0.0


def test_compute_backoff_delay_exponential_without_jitter():
    rng = _ZeroJitterRng()
    assert compute_backoff_delay(0, base=10, max_delay=120, rng=rng) == 10
    assert compute_backoff_delay(1, base=10, max_delay=120, rng=rng) == 20
    assert compute_backoff_delay(2, base=10, max_delay=120, rng=rng) == 40
    assert compute_backoff_delay(3, base=10, max_delay=120, rng=rng) == 80


def test_compute_backoff_delay_caps_at_max_delay():
    rng = _ZeroJitterRng()
    assert compute_backoff_delay(10, base=10, max_delay=120, rng=rng) == 120


def test_compute_backoff_delay_applies_jitter_within_bounds():
    for attempt in range(5):
        delay = compute_backoff_delay(attempt, base=10, max_delay=120, jitter_fraction=0.2)
        expected = min(10 * (2 ** attempt), 120)
        assert expected * 0.8 <= delay <= expected * 1.2


def test_compute_backoff_delay_never_negative():
    delay = compute_backoff_delay(0, base=1, max_delay=120, jitter_fraction=5.0)
    assert delay >= 0


def test_reconnect_attempt_resets_on_connack():
    client = _client_with_creds()
    client._reconnect_attempt = 5

    client._on_message(None, b"\x20\x02\x00\x00")

    assert client._reconnect_attempt == 0
