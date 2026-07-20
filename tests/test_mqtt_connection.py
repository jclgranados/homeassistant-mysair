"""Tests P0/P1 de la robustez de conexión MQTT (client_id, topic, expiración).

Sin Home Assistant. Requiere websocket-client (mqtt_handler) y requests (api).
"""

import time

import pytest

pytest.importorskip("websocket")
pytest.importorskip("requests")

from mqtt_handler import build_client_id, build_status_topic
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
