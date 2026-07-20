"""Fixtures y utilidades compartidas para los tests que no requieren Home Assistant.

Inserta ``custom_components/mysair`` en sys.path para poder importar los módulos
puros (status_parser, api, mqtt_handler) COMO módulos de nivel superior, es decir
sin ejecutar el ``__init__.py`` del paquete (que depende de homeassistant).
Esto funciona porque esos módulos no tienen imports relativos.
Todos los datos de fixtures están SANITIZADOS (valores ficticios, sin secretos).
"""

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO_ROOT, "custom_components", "mysair"))
# Necesario para que el harness de HA (Docker) pueda hacer `import
# custom_components` como paquete namespace y descubrir `custom_components/mysair`
# (ver homeassistant.loader._get_custom_components).
sys.path.insert(0, _REPO_ROOT)

import pytest

try:
    import pytest_homeassistant_custom_component  # noqa: F401

    _HA_TEST_HARNESS_AVAILABLE = True
except ImportError:
    _HA_TEST_HARNESS_AVAILABLE = False

if _HA_TEST_HARNESS_AVAILABLE:
    # Solo se define cuando el harness de HA está instalado (Docker, ver
    # Dockerfile.test). Al montar el fixture hass(), pytest-homeassistant-
    # custom-component importa SU PROPIO paquete `custom_components` de
    # prueba (un paquete regular, no namespace) y lo deja cacheado en
    # sys.modules con __path__ apuntando solo a esa carpeta interna. Como
    # __path__ es una lista mutable, añadimos nuestra carpeta real para que
    # `homeassistant.loader` encuentre también custom_components/mysair.
    @pytest.fixture(autouse=True)
    def auto_enable_custom_integrations(hass, enable_custom_integrations):
        import custom_components as _test_custom_components

        our_custom_components_dir = os.path.join(_REPO_ROOT, "custom_components")
        if our_custom_components_dir not in _test_custom_components.__path__:
            _test_custom_components.__path__.append(our_custom_components_dir)
        yield


class FakeResponse:
    """Imitación mínima de requests.Response."""

    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json = {} if json_data is None else json_data
        self.text = text

    def json(self):
        return self._json


class FakeSession:
    """Sesión requests falsa: devuelve respuestas encoladas por método y registra llamadas.

    Uso:
        s = FakeSession()
        s.queue("post", FakeResponse(200, {...}))
        api = MySairAPI("e", "p", session=s)
        ...
        assert s.calls[-1]["json"] == [...]
    """

    def __init__(self):
        self.responses = {"get": [], "post": [], "put": []}
        self.calls = []

    def queue(self, method, *responses):
        self.responses[method].extend(responses)
        return self

    def _handle(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        queue = self.responses[method]
        if not queue:
            raise AssertionError(f"Sin respuesta encolada para {method.upper()} {url}")
        return queue.pop(0)

    def get(self, url, **kwargs):
        return self._handle("get", url, **kwargs)

    def post(self, url, **kwargs):
        return self._handle("post", url, **kwargs)

    def put(self, url, **kwargs):
        return self._handle("put", url, **kwargs)


@pytest.fixture
def make_response():
    def _make(status_code=200, json_data=None, text=""):
        return FakeResponse(status_code, json_data, text)

    return _make


@pytest.fixture
def fake_session():
    return FakeSession()


# --- Payloads sanitizados (solo campos que el código realmente consume) ---

@pytest.fixture
def login_ok():
    return {"entity": {"access_token": "TEST_ACCESS", "refresh_token": "TEST_REFRESH"}}


@pytest.fixture
def aws_credentials_ok():
    return {
        "entity": {
            "aws_mqtt_host": "test.iot.eu-west-1.amazonaws.com",
            "aws_default_region": "eu-west-1",
            "aws_access_key_id": "TESTKEYID",
            "aws_secret_access_key": "TESTSECRET",
            "aws_security_token": "TESTTOKEN",
            "aws_mqtt_user": "web0000",
        }
    }


@pytest.fixture
def status_payload():
    """Payload MQTT 'status' con value como string JSON y ';' final (como en producción).

    Campos (ver docs/protocol-findings.md): e=encendido, m=modo (0=AC calor),
    tr/tc/tmm/tmx=temperaturas, hum=humedad (confirmado en producción
    2026-07-20; "hm" se mantiene como fallback), c/f/v/s=capacidades.
    """
    return {
        "ctl": "INST_A",
        "value": (
            '{"t":[{"rf":"DEV_1","n":"Salon","e":"1","m":"0",'
            '"tr":22.5,"tc":21.0,"tmm":10.0,"tmx":30.0,"hum":45,'
            '"vv":"0","c":"1","f":"1","v":"0","s":"0"}]};'
        ),
    }
