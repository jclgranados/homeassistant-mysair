"""Tests P0 de los constructores de paquetes MQTT (sin Home Assistant).

Requiere que `websocket-client` esté instalado (mqtt_handler lo importa a nivel
de módulo); si no lo está, se omiten.
"""

import struct

import pytest

pytest.importorskip("websocket")

from mqtt_handler import build_mqtt_connect, build_mqtt_subscribe, encode_varint


@pytest.mark.parametrize(
    "value,expected",
    [
        (0, b"\x00"),
        (127, b"\x7f"),
        (128, b"\x80\x01"),
        (16383, b"\xff\x7f"),
        (16384, b"\x80\x80\x01"),
    ],
)
def test_encode_varint(value, expected):
    assert encode_varint(value) == expected


def test_build_mqtt_connect_structure():
    pkt = build_mqtt_connect("cid", "usr", "pwd")
    # Tipo CONNECT
    assert pkt[0:1] == b"\x10"
    # Cabecera variable: nombre de protocolo MQTT v3.1.1, flags 0xC2, keepalive 60
    assert b"\x00\x04MQTT\x04\xc2" + struct.pack("!H", 60) in pkt
    # Campos del payload con prefijo de longitud
    assert struct.pack("!H", 3) + b"cid" in pkt
    assert struct.pack("!H", 3) + b"usr" in pkt
    assert struct.pack("!H", 3) + b"pwd" in pkt


def test_build_mqtt_connect_remaining_length():
    pkt = build_mqtt_connect("a", "b", "c")
    remaining = encode_varint(len(pkt) - 2)  # total menos el fixed header (0x10 + 1 byte len)
    assert pkt[1:2] == remaining


def test_build_mqtt_subscribe_structure():
    topic = "pro/v1/get/ctl/INST_A/#"
    pkt = build_mqtt_subscribe(1, topic)
    # Tipo SUBSCRIBE (0x82 incluye el flag obligatorio 0x02)
    assert pkt[0:1] == b"\x82"
    # packet_id
    assert struct.pack("!H", 1) in pkt
    # topic con prefijo de longitud y QoS 0 al final
    assert struct.pack("!H", len(topic)) + topic.encode() + b"\x00" in pkt
    assert pkt[-1:] == b"\x00"  # QoS 0


def test_build_mqtt_subscribe_packet_id_varies():
    p1 = build_mqtt_subscribe(1, "t")
    p2 = build_mqtt_subscribe(2, "t")
    assert p1 != p2
    assert struct.pack("!H", 2) in p2
