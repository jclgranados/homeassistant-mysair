"""Tests P0 de la firma de URL AWS SigV4 (sin Home Assistant).

Requiere `requests` (api lo importa) y `freezegun` para fijar el reloj.
No valida contra AWS: solo la estructura y el determinismo de la firma.
"""

import re
import urllib.parse

import pytest

pytest.importorskip("requests")
freezegun = pytest.importorskip("freezegun")

from api import MySairAPI  # noqa: E402 (deliberado: necesita importorskip antes)


FIXED = "2026-07-19T10:00:00Z"


def _sign():
    return MySairAPI.aws_sign_url(
        host="test.iot.eu-west-1.amazonaws.com",
        region="eu-west-1",
        access_key="TESTKEYID",
        secret_key="TESTSECRET",
        token="TESTTOKEN",
    )


def test_signed_url_structure():
    with freezegun.freeze_time(FIXED):
        url = _sign()
    assert url.startswith("wss://test.iot.eu-west-1.amazonaws.com/mqtt?")
    qs = urllib.parse.parse_qs(url.split("?", 1)[1])
    assert qs["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]
    assert qs["X-Amz-SignedHeaders"] == ["host"]
    assert qs["X-Amz-Security-Token"] == ["TESTTOKEN"]
    # Credential incluye el scope con region y servicio iotdevicegateway
    cred = qs["X-Amz-Credential"][0]
    assert "TESTKEYID/" in cred
    assert "eu-west-1/iotdevicegateway/aws4_request" in cred
    # La firma es un hex SHA256 de 64 caracteres
    assert re.fullmatch(r"[0-9a-f]{64}", qs["X-Amz-Signature"][0])


def test_signature_is_deterministic_for_fixed_time():
    with freezegun.freeze_time(FIXED):
        url1 = _sign()
    with freezegun.freeze_time(FIXED):
        url2 = _sign()
    assert url1 == url2


def test_amz_date_matches_frozen_time():
    with freezegun.freeze_time(FIXED):
        url = _sign()
    qs = urllib.parse.parse_qs(url.split("?", 1)[1])
    assert qs["X-Amz-Date"] == ["20260719T100000Z"]
