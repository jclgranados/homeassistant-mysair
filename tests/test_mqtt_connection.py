"""Tests P0/P1 de la robustez de conexión MQTT (client_id, topic, expiración).

Sin Home Assistant. Requiere websocket-client (mqtt_handler) y requests (api).
"""

import time

import pytest

pytest.importorskip("websocket")
pytest.importorskip("requests")

from mqtt_handler import build_client_id, build_status_topic, build_feedback_topic, MySairMQTTClient
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
