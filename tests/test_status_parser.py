"""Tests P0 del parser puro de mensajes 'status' (sin Home Assistant).

Semántica confirmada desde la app oficial (docs/protocol-findings.md):
  - e = encendido: "0"=off, "1"=on, "2"=standby
  - m = modo 0-5: par=calor, impar=frío; {0,1,4,5}=AC, {2,3,4,5}=suelo
"""

import pytest

from status_parser import (
    compute_mode_value,
    parse_mode,
    parse_status_payload,
    parse_status_value,
    parse_feedback_payload,
)


# --- parse_status_value ---


def test_parse_status_value_string_with_trailing_semicolon():
    assert parse_status_value('{"a":1};') == {"a": 1}


def test_parse_status_value_plain_string_json():
    assert parse_status_value('{"a":1}') == {"a": 1}


def test_parse_status_value_dict_passthrough():
    assert parse_status_value({"a": 1}) == {"a": 1}


def test_parse_status_value_invalid_json_returns_empty():
    assert parse_status_value("no-json") == {}


def test_parse_status_value_non_str_non_dict_returns_empty():
    assert parse_status_value(None) == {}
    assert parse_status_value(123) == {}
    assert parse_status_value(["x"]) == {}


def test_parse_status_value_json_non_object_returns_empty():
    assert parse_status_value("[1,2,3]") == {}


# --- parse_mode ---


@pytest.mark.parametrize(
    "m,expected",
    [
        ("0", ("0", True, False, True, False)),  # AC calor
        ("1", ("1", False, True, True, False)),  # AC frío
        ("2", ("2", True, False, False, True)),  # suelo calor
        ("3", ("3", False, True, False, True)),  # suelo frío
        ("4", ("4", True, False, True, True)),  # AC+suelo calor
        ("5", ("5", False, True, True, True)),  # AC+suelo frío
        (0, ("0", True, False, True, False)),  # int también válido
    ],
)
def test_parse_mode_values(m, expected):
    assert parse_mode(m) == expected


def test_parse_mode_none():
    assert parse_mode(None) == (None, None, None, None, None)


def test_parse_mode_non_numeric():
    assert parse_mode("x") == ("x", None, None, None, None)


# --- compute_mode_value (F4, inversa de parse_mode) ---


@pytest.mark.parametrize(
    "is_heat,is_ac,is_floor,expected",
    [
        (True, True, False, "0"),  # AC calor
        (False, True, False, "1"),  # AC frío
        (True, False, True, "2"),  # suelo calor
        (False, False, True, "3"),  # suelo frío
        (True, True, True, "4"),  # AC+suelo calor
        (False, True, True, "5"),  # AC+suelo frío
    ],
)
def test_compute_mode_value_matches_confirmed_table(is_heat, is_ac, is_floor, expected):
    assert compute_mode_value(is_heat, is_ac, is_floor) == expected


def test_compute_mode_value_roundtrips_with_parse_mode():
    for m in ("0", "1", "2", "3", "4", "5"):
        _, is_heat, _, is_ac, is_floor = parse_mode(m)
        assert compute_mode_value(is_heat, is_ac, is_floor) == m


def test_compute_mode_value_forces_ac_when_neither_medium_active():
    # Combinación que la app nunca genera: se fuerza AC=True en vez de
    # enviar un 'm' nunca visto en el bundle.
    assert compute_mode_value(is_heat=True, is_ac=False, is_floor=False) == "0"


# --- parse_status_payload ---


def test_parse_status_payload_full(status_payload):
    result = parse_status_payload(status_payload)
    assert result["ctl"] == "INST_A"
    assert len(result["zones"]) == 1
    zone = result["zones"][0]
    assert zone == {
        "ctl": "INST_A",
        "zone_id": "DEV_1",
        "zone_name": "Salon",
        "temp_actual": 22.5,
        "temp_target": 21.0,
        "temp_min": 10.0,
        "temp_max": 30.0,
        "humidity": 45.0,
        "power": "1",
        "is_on": True,
        "is_standby": False,
        "mode_raw": "0",
        "is_heat": True,
        "is_cool": False,
        "is_ac": True,
        "is_floor": False,
        "fan_mode": "0",
        "allow_heat": True,
        "allow_cool": True,
        "allow_fan": False,
        "allow_floor": False,
    }


@pytest.mark.parametrize(
    "e,is_on,is_standby",
    [("0", False, False), ("1", True, False), ("2", True, True)],
)
def test_parse_status_payload_power_field(e, is_on, is_standby):
    payload = {"ctl": "X", "value": '{"t":[{"rf":"D","e":"%s","m":"0"}]}' % e}
    zone = parse_status_payload(payload)["zones"][0]
    assert zone["is_on"] is is_on
    assert zone["is_standby"] is is_standby


def test_parse_status_payload_cool_mode():
    # m=1 (AC frío), encendido
    payload = {"ctl": "X", "value": '{"t":[{"rf":"D","e":"1","m":"1"}]}'}
    zone = parse_status_payload(payload)["zones"][0]
    assert zone["is_on"] is True
    assert zone["is_heat"] is False
    assert zone["is_cool"] is True


def test_parse_status_payload_off_keeps_mode_field():
    # apagado (e="0") pero m sigue presente: is_on False, y m interpretable
    payload = {"ctl": "X", "value": '{"t":[{"rf":"D","e":"0","m":"1"}]}'}
    zone = parse_status_payload(payload)["zones"][0]
    assert zone["is_on"] is False
    assert zone["mode_raw"] == "1"
    assert zone["is_cool"] is True


def test_parse_status_payload_missing_mode_is_none():
    payload = {"ctl": "X", "value": '{"t":[{"rf":"D","e":"1"}]}'}
    zone = parse_status_payload(payload)["zones"][0]
    assert zone["is_on"] is True
    assert zone["mode_raw"] is None
    assert zone["is_heat"] is None
    assert zone["is_cool"] is None


def test_parse_status_payload_missing_temps_are_none():
    payload = {"ctl": "X", "value": '{"t":[{"rf":"D","e":"1","m":"0"}]}'}
    zone = parse_status_payload(payload)["zones"][0]
    assert zone["temp_actual"] is None
    assert zone["temp_target"] is None
    assert zone["humidity"] is None


def test_parse_status_payload_humidity_reads_hum_field():
    # Campo real confirmado en producción (2026-07-20): "hum", no "hm".
    payload = {"ctl": "X", "value": '{"t":[{"rf":"D","e":"1","m":"0","hum":"55"}]}'}
    zone = parse_status_payload(payload)["zones"][0]
    assert zone["humidity"] == 55.0


def test_parse_status_payload_humidity_falls_back_to_hm_field():
    # "hm" como fallback defensivo por si alguna variante del backend lo usa.
    payload = {"ctl": "X", "value": '{"t":[{"rf":"D","e":"1","m":"0","hm":"40"}]}'}
    zone = parse_status_payload(payload)["zones"][0]
    assert zone["humidity"] == 40.0


def test_parse_status_payload_default_power_off_when_missing_e():
    payload = {"ctl": "X", "value": '{"t":[{"rf":"D"}]}'}
    zone = parse_status_payload(payload)["zones"][0]
    assert zone["power"] == "0"
    assert zone["is_on"] is False


def test_parse_status_payload_invalid_value_yields_no_zones():
    assert parse_status_payload({"ctl": "X", "value": "no-json"}) == {
        "ctl": "X",
        "zones": [],
    }


def test_parse_status_payload_missing_value():
    assert parse_status_payload({"ctl": "Z"}) == {"ctl": "Z", "zones": []}


def test_parse_status_payload_non_dict_input():
    # E4: un payload que no es ni siquiera un dict se rechaza (None), en vez
    # de devolver un dict "vacío" que de todas formas no hace nada aguas abajo.
    assert parse_status_payload(None) is None


def test_parse_status_payload_non_dict_input_logs_warning(caplog):
    caplog.set_level("WARNING")
    parse_status_payload(None)
    assert "no es un dict" in caplog.text


def test_parse_status_payload_t_not_a_list_logs_warning_and_yields_no_zones(caplog):
    caplog.set_level("WARNING")
    payload = {"ctl": "X", "value": '{"t": 42}'}

    result = parse_status_payload(payload)

    assert result == {"ctl": "X", "zones": []}
    assert "campo 't' con forma inesperada" in caplog.text


def test_parse_status_payload_missing_ctl_logs_warning(caplog):
    caplog.set_level("WARNING")
    payload = {"value": '{"t":[{"rf":"D1","e":"1","m":"0"}]}'}

    result = parse_status_payload(payload)

    assert result["ctl"] is None
    assert "sin 'ctl'" in caplog.text


def test_parse_status_payload_zone_missing_rf_logs_warning(caplog):
    caplog.set_level("WARNING")
    payload = {"ctl": "X", "value": '{"t":[{"e":"1","m":"0"}]}'}

    zones = parse_status_payload(payload)["zones"]

    assert len(zones) == 1
    assert zones[0]["zone_id"] is None
    assert "zona sin 'rf'" in caplog.text


def test_parse_status_payload_skips_non_dict_thermostats():
    payload = {"ctl": "X", "value": '{"t":["bogus",{"rf":"D1","e":"1","m":"0"}]}'}
    zones = parse_status_payload(payload)["zones"]
    assert len(zones) == 1
    assert zones[0]["zone_id"] == "D1"


# --- parse_feedback_payload (topic .../feedback, known-unknowns #23) ---


def test_parse_feedback_payload_flat_form():
    payload = {"orderId": "abc-123", "ctl": "INST_A"}
    assert parse_feedback_payload(payload) == {
        "order_id": "abc-123",
        "ctl": "INST_A",
        "raw": payload,
    }


def test_parse_feedback_payload_nested_value_fallback():
    payload = {"ctl": "INST_A", "value": '{"orderId":"abc-123","ctl":"INST_A"};'}
    result = parse_feedback_payload(payload)
    assert result["order_id"] == "abc-123"
    assert result["ctl"] == "INST_A"


def test_parse_feedback_payload_missing_fields():
    result = parse_feedback_payload({"foo": "bar"})
    assert result["order_id"] is None
    assert result["ctl"] is None


def test_parse_feedback_payload_non_dict_input():
    # E4: rechazado (None) en vez de un dict con raw preservado.
    assert parse_feedback_payload("not-a-dict") is None


def test_parse_feedback_payload_non_dict_input_logs_warning(caplog):
    caplog.set_level("WARNING")
    parse_feedback_payload("not-a-dict")
    assert "no es un dict" in caplog.text


def test_parse_feedback_payload_missing_order_id_and_ctl_logs_warning(caplog):
    caplog.set_level("WARNING")
    result = parse_feedback_payload({"unrelated": "field"})

    assert result == {"order_id": None, "ctl": None, "raw": {"unrelated": "field"}}
    assert "no se encontró" in caplog.text
