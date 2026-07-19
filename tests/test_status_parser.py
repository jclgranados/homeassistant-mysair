"""Tests P0 del parser puro de mensajes 'status' (sin Home Assistant)."""

from status_parser import parse_status_payload, parse_status_value


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
    # Un JSON válido pero que no es objeto (p. ej. una lista) se normaliza a {}
    assert parse_status_value("[1,2,3]") == {}


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
        "mode": 1,
    }


def test_parse_status_payload_missing_fields_use_defaults():
    payload = {"ctl": "X", "value": '{"t":[{"rf":"D1"}]}'}
    zone = parse_status_payload(payload)["zones"][0]
    assert zone["zone_id"] == "D1"
    assert zone["zone_name"] is None
    assert zone["temp_actual"] == 0.0
    assert zone["temp_target"] == 0.0
    assert zone["mode"] == 0


def test_parse_status_payload_invalid_value_yields_no_zones():
    assert parse_status_payload({"ctl": "X", "value": "no-json"}) == {"ctl": "X", "zones": []}


def test_parse_status_payload_missing_value():
    assert parse_status_payload({"ctl": "Z"}) == {"ctl": "Z", "zones": []}


def test_parse_status_payload_non_dict_input():
    assert parse_status_payload(None) == {"ctl": None, "zones": []}


def test_parse_status_payload_mode_mapping():
    # Mapeo asumido de 'e': 0=off, 1=heat, 2=cool (ver docs/known-unknowns.md #2)
    for e_value, expected in [(0, 0), (1, 1), (2, 2)]:
        payload = {"ctl": "X", "value": '{"t":[{"rf":"D","e":%d}]}' % e_value}
        assert parse_status_payload(payload)["zones"][0]["mode"] == expected


def test_parse_status_payload_skips_non_dict_thermostats():
    payload = {"ctl": "X", "value": '{"t":["bogus",{"rf":"D1","e":1}]}'}
    zones = parse_status_payload(payload)["zones"]
    assert len(zones) == 1
    assert zones[0]["zone_id"] == "D1"
