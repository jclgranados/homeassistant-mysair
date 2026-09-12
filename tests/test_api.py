"""Tests P1 del cliente HTTP MySairAPI con una sesión inyectada (sin red)."""

import pytest

pytest.importorskip("requests")

from api import MySairAPI, MySairAuthError, MySairConnectionError, extract_order_id


def _api(session):
    return MySairAPI("user@example.com", "secret", session=session)


# --- LOGIN ---


def test_login_success(fake_session, make_response, login_ok):
    fake_session.queue("post", make_response(200, login_ok))
    api = _api(fake_session)
    assert api.login() is True
    assert api.access_token == "TEST_ACCESS"
    assert api.refresh_token_value == "TEST_REFRESH"
    assert fake_session.calls[-1]["url"].endswith("/user/login")


def test_login_http_error_raises(fake_session, make_response):
    fake_session.queue("post", make_response(500, {}, "boom"))
    with pytest.raises(Exception):
        _api(fake_session).login()


def test_login_missing_token_raises(fake_session, make_response):
    fake_session.queue("post", make_response(200, {"entity": {}}))
    with pytest.raises(Exception):
        _api(fake_session).login()


def test_login_invalid_credentials_raises_auth_error(fake_session, make_response):
    fake_session.queue("post", make_response(401, {}, "unauthorized"))
    with pytest.raises(MySairAuthError):
        _api(fake_session).login()


def test_login_backend_error_raises_connection_error(fake_session, make_response):
    fake_session.queue("post", make_response(500, {}, "boom"))
    with pytest.raises(MySairConnectionError):
        _api(fake_session).login()


def test_login_notifies_tokens_callback(fake_session, make_response, login_ok):
    fake_session.queue("post", make_response(200, login_ok))
    calls = []
    api = MySairAPI(
        "user@example.com",
        "secret",
        session=fake_session,
        on_tokens_refreshed=lambda access, refresh: calls.append((access, refresh)),
    )
    api.login()
    assert calls == [("TEST_ACCESS", "TEST_REFRESH")]


def test_login_callback_error_does_not_break_login(
    fake_session, make_response, login_ok
):
    fake_session.queue("post", make_response(200, login_ok))

    def boom(access, refresh):
        raise RuntimeError("callback roto")

    api = MySairAPI(
        "user@example.com", "secret", session=fake_session, on_tokens_refreshed=boom
    )
    assert api.login() is True


# --- REFRESH TOKENS ---


def test_refresh_tokens_without_value_raises_auth_error(fake_session):
    api = _api(fake_session)
    api.refresh_token_value = None
    with pytest.raises(MySairAuthError):
        api.refresh_tokens()


def test_refresh_tokens_invalid_raises_auth_error(fake_session, make_response):
    fake_session.queue("put", make_response(401, {}, "unauthorized"))
    api = _api(fake_session)
    api.refresh_token_value = "OLD_REFRESH"
    with pytest.raises(MySairAuthError):
        api.refresh_tokens()


def test_refresh_tokens_backend_error_raises_connection_error(
    fake_session, make_response
):
    fake_session.queue("put", make_response(500, {}, "boom"))
    api = _api(fake_session)
    api.refresh_token_value = "OLD_REFRESH"
    with pytest.raises(MySairConnectionError):
        api.refresh_tokens()


def test_refresh_tokens_revoked_token_raises_auth_error(fake_session, make_response):
    """Regresión del incidente del 2026-09-11.

    MySair corre sobre Laravel Passport, que responde **404** (no 401) cuando
    el refresh_token ya no existe en servidor. Se clasificaba como error de
    conexión → ConfigEntryNotReady → Home Assistant reintentaba en bucle sin
    ofrecer nunca el reauth, y la única salida era desinstalar la integración.
    """
    fake_session.queue(
        "put",
        make_response(
            404, {}, "No query results for model [Laravel\\Passport\\RefreshToken]"
        ),
    )
    api = _api(fake_session)
    api.refresh_token_value = "REVOKED_REFRESH"
    with pytest.raises(MySairAuthError):
        api.refresh_tokens()


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_client_errors_classified_as_auth(fake_session, make_response, status):
    """Un 4xx en un endpoint de sesión significa siempre 'pide credenciales'."""
    fake_session.queue("put", make_response(status, {}, "nope"))
    api = _api(fake_session)
    api.refresh_token_value = "OLD_REFRESH"
    with pytest.raises(MySairAuthError):
        api.refresh_tokens()


@pytest.mark.parametrize("status", [429, 500, 502, 503])
def test_server_errors_classified_as_connection(fake_session, make_response, status):
    """5xx y 429 son transitorios: reintentar sí tiene sentido."""
    fake_session.queue("put", make_response(status, {}, "boom"))
    api = _api(fake_session)
    api.refresh_token_value = "OLD_REFRESH"
    with pytest.raises(MySairConnectionError):
        api.refresh_tokens()


def test_refresh_tokens_ok_notifies_callback(fake_session, make_response):
    fake_session.queue(
        "put",
        make_response(
            200, {"entity": {"access_token": "NEW", "refresh_token": "NEW_R"}}
        ),
    )
    calls = []
    api = MySairAPI(
        "user@example.com",
        session=fake_session,
        on_tokens_refreshed=lambda access, refresh: calls.append((access, refresh)),
    )
    api.refresh_token_value = "OLD_REFRESH"
    assert api.refresh_tokens() is True
    assert api.access_token == "NEW"
    assert calls == [("NEW", "NEW_R")]


def test_api_works_without_password():
    # A6: la API debe poder construirse sin password (solo refresh_token en runtime).
    api = MySairAPI("user@example.com")
    assert api.password is None


# --- DESCUBRIMIENTO ---


def test_get_locations_ok(fake_session, make_response):
    fake_session.queue("get", make_response(200, {"entity": [{"id": 1001}]}))
    assert _api(fake_session).get_locations() == [{"id": 1001}]


def test_get_locations_backend_error_raises_connection_error(
    fake_session, make_response
):
    # Antes devolvía [] ante cualquier fallo, indistinguible de una cuenta
    # vacía: el setup lo leía como "sin ubicaciones" y reintentaba en bucle.
    fake_session.queue("get", make_response(500, {}, "err"))
    with pytest.raises(MySairConnectionError):
        _api(fake_session).get_locations()


def test_get_locations_dead_session_raises_auth_error(fake_session, make_response):
    fake_session.queue("get", make_response(404, {}, "not found"))
    with pytest.raises(MySairAuthError):
        _api(fake_session).get_locations()


def test_get_locations_retries_once_after_refreshing_tokens(
    fake_session, make_response, login_ok
):
    # 401 aislado: el access_token caducó pero la sesión sigue viva.
    fake_session.queue(
        "get",
        make_response(401, {}, "expired"),
        make_response(200, {"entity": [{"id": 1001}]}),
    )
    fake_session.queue("put", make_response(200, login_ok))
    api = _api(fake_session)
    api.refresh_token_value = "TEST_REFRESH"
    assert api.get_locations() == [{"id": 1001}]
    assert any("/user/refreshtokens" in c["url"] for c in fake_session.calls)


def test_get_locations_gives_up_if_refresh_also_fails(fake_session, make_response):
    fake_session.queue("get", make_response(401, {}, "expired"))
    fake_session.queue("put", make_response(404, {}, "No query results"))
    api = _api(fake_session)
    api.refresh_token_value = "DEAD"
    with pytest.raises(MySairAuthError):
        api.get_locations()


def test_get_installations_url_has_params(fake_session, make_response):
    fake_session.queue("get", make_response(200, {"entity": []}))
    _api(fake_session).get_installations(1001)
    url = fake_session.calls[-1]["url"]
    assert "location_id=1001" in url
    assert "validated=1" in url


def test_get_devices_ok(fake_session, make_response):
    devices = [{"reference": "DEV_1", "name": "Salon"}]
    fake_session.queue("get", make_response(200, {"entity": devices}))
    assert _api(fake_session).get_devices("INST_A") == devices
    assert "installation_ref=INST_A" in fake_session.calls[-1]["url"]


# --- SEND INSTRUCTION ---


def _creado(make_response):
    return make_response(201, {"msg": "Creado", "error": []})


def test_send_instruction_ok(fake_session, make_response):
    fake_session.queue("post", _creado(make_response))
    data = _api(fake_session).send_instruction([{"command": "status"}])
    assert data["msg"] == "Creado"


def test_send_instruction_rejected_msg_raises(fake_session, make_response):
    fake_session.queue("post", make_response(201, {"msg": "Rechazado", "error": []}))
    with pytest.raises(Exception):
        _api(fake_session).send_instruction([{"command": "x"}])


def test_send_instruction_error_status_raises(fake_session, make_response):
    fake_session.queue("post", make_response(500, {}, "err"))
    with pytest.raises(Exception):
        _api(fake_session).send_instruction([{"command": "x"}])


def test_send_instruction_401_refreshes_and_retries(
    fake_session, make_response, aws_credentials_ok
):
    fake_session.queue("post", make_response(401, {}), _creado(make_response))
    fake_session.queue(
        "put",
        make_response(
            200, {"entity": {"access_token": "NEW", "refresh_token": "NEW_R"}}
        ),
        make_response(200, aws_credentials_ok),
    )
    api = _api(fake_session)
    api.access_token = "OLD"
    api.refresh_token_value = "TEST_REFRESH"

    data = api.send_instruction([{"command": "x"}])

    assert data["msg"] == "Creado"
    assert api.access_token == "NEW"
    assert api.aws_credentials["aws_mqtt_user"] == "web0000"
    methods = [c["method"] for c in fake_session.calls]
    assert methods == ["post", "put", "put", "post"]


def test_send_instruction_401_without_refresh_token_raises(fake_session, make_response):
    fake_session.queue("post", make_response(401, {}))
    api = _api(fake_session)
    api.refresh_token_value = (
        None  # refresh_tokens() lanza MySairAuthError → sin reintento
    )
    with pytest.raises(Exception):
        api.send_instruction([{"command": "x"}])


# --- SEND ZONE COMMAND ---


def test_send_zone_command_mode(fake_session, make_response):
    fake_session.queue("post", _creado(make_response))
    _api(fake_session).send_zone_command("INST", "DEV", "mode", "0", 21.0)
    body = fake_session.calls[-1]["json"][0]
    assert body == {
        "sender": "WEB",
        "ctl": "INST",
        "app": "web0077",  # sin aws_credentials → fallback
        "device": "DEV",
        "command": "mode",
        "value": {"mode": "0", "temperature": "21.0"},
    }


def test_send_zone_command_temp(fake_session, make_response):
    fake_session.queue("post", _creado(make_response))
    _api(fake_session).send_zone_command("INST", "DEV", "temp", 22.5)
    body = fake_session.calls[-1]["json"][0]
    assert body["command"] == "temp"
    assert body["value"] == "22.5"


def test_send_zone_command_power(fake_session, make_response):
    fake_session.queue("post", _creado(make_response))
    _api(fake_session).send_zone_command("INST", "DEV", "power")
    body = fake_session.calls[-1]["json"][0]
    assert body["command"] == "power"
    assert body["value"] == "0"


def test_send_zone_command_fanspeed(fake_session, make_response):
    fake_session.queue("post", _creado(make_response))
    _api(fake_session).send_zone_command("INST", "DEV", "fanspeed", "4")
    body = fake_session.calls[-1]["json"][0]
    assert body["command"] == "fanspeed"
    assert body["value"] == "4"


def test_send_zone_command_fanspeed_invalid_value_raises(fake_session):
    with pytest.raises(ValueError):
        _api(fake_session).send_zone_command("INST", "DEV", "fanspeed", "9")


def test_send_zone_command_invalid_mode_raises(fake_session):
    with pytest.raises(ValueError):
        _api(fake_session).send_zone_command("INST", "DEV", "mode", "5")


def test_send_zone_command_missing_params_raises(fake_session):
    with pytest.raises(ValueError):
        _api(fake_session).send_zone_command("", "DEV", "power")


# --- send_installation_command (F5, servicio stop_installation) ---


def test_send_installation_command_stop(fake_session, make_response):
    fake_session.queue("post", _creado(make_response))
    _api(fake_session).send_installation_command("INST", "stop")
    body = fake_session.calls[-1]["json"][0]
    assert body == {
        "sender": "WEB",
        "ctl": "INST",
        "app": "web0077",
        "device": "",
        "command": "stop",
        "value": "1",
    }


def test_send_installation_command_status(fake_session, make_response):
    fake_session.queue("post", _creado(make_response))
    _api(fake_session).send_installation_command("INST", "status")
    body = fake_session.calls[-1]["json"][0]
    assert body["command"] == "status"
    assert body["value"] == "sync"


def test_send_installation_command_invalid_type_raises(fake_session):
    with pytest.raises(ValueError):
        _api(fake_session).send_installation_command("INST", "bogus")


def test_send_installation_command_missing_ctl_raises(fake_session):
    with pytest.raises(ValueError):
        _api(fake_session).send_installation_command("", "stop")


# --- extract_order_id (E7, confirmación de comandos) ---


def test_extract_order_id_ok():
    response = {
        "msg": "Creado",
        "error": [],
        "entity": {"value": [{"orderId": "abc-123"}]},
    }
    assert extract_order_id(response) == "abc-123"


def test_extract_order_id_missing_entity_returns_none():
    assert extract_order_id({"msg": "Creado", "error": []}) is None


def test_extract_order_id_empty_value_list_returns_none():
    assert extract_order_id({"entity": {"value": []}}) is None


def test_extract_order_id_non_dict_returns_none():
    assert extract_order_id(None) is None
    assert extract_order_id("not-a-dict") is None
