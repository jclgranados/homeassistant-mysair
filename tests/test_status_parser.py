"""Tests P0 del parser puro de mensajes 'status' (sin Home Assistant).

Semántica confirmada desde la app oficial (docs/protocol-findings.md):
  - e = encendido: "0"=off, "1"=on, "2"=standby
  - m = modo 0-5: par=calor, impar=frío; {0,1,4,5}=AC, {2,3,4,5}=suelo
"""

import pytest

from status_parser import parse_mode, parse_status_payload, parse_status_value


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
        ("0", ("0", True, False, True, False)),   # AC calor
        ("1", ("1", False, True, True, False)),   # AC frío
        ("2", ("2", True, False, False, True)),   # suelo calor
        ("3", ("3", False, True, False, True)),   # suelo frío
        ("4", ("4", True, False, True, True)),    # AC+suelo calor
        ("5", ("5", False, True, True, True)),    # AC+suelo frío
        (0, ("0", True, False, True, False)),     # int también válido
    ],
)
def test_parse_mode_values(m, expected):
    assert parse_mode(m) == expected


def test_parse_mode_none():
    assert parse_mode(None) == (None, None, None, None, None)


def test_parse_mode_non_numeric():
    assert parse_mode("x") == ("x", None, None, None, None)


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


def test_parse_status_payload_default_power_off_when_missing_e():
    payload = {"ctl": "X", "value": '{"t":[{"rf":"D"}]}'}
    zone = parse_status_payload(payload)["zones"][0]
    assert zone["power"] == "0"
    assert zone["is_on"] is False


def test_parse_status_payload_invalid_value_yields_no_zones():
    assert parse_status_payload({"ctl": "X", "value": "no-json"}) == {"ctl": "X", "zones": []}


def test_parse_status_payload_missing_value():
    assert parse_status_payload({"ctl": "Z"}) == {"ctl": "Z", "zones": []}


def test_parse_status_payload_non_dict_input():
    assert parse_status_payload(None) == {"ctl": None, "zones": []}


def test_parse_status_payload_skips_non_dict_thermostats():
    payload = {"ctl": "X", "value": '{"t":["bogus",{"rf":"D1","e":"1","m":"0"}]}'}
    zones = parse_status_payload(payload)["zones"]
    assert len(zones) == 1
    assert zones[0]["zone_id"] == "D1"
