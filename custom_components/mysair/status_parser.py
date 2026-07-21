"""Parsers puros para los mensajes MQTT de MySair.

Este módulo NO depende de Home Assistant a propósito: así la lógica de parseo
del estado se puede importar y testear de forma aislada (ver docs/testing-strategy.md).
"""

import json
import logging

_LOGGER = logging.getLogger(__name__)


def parse_status_value(raw_value):
    """Decodifica el campo ``value`` de un mensaje ``status``.

    El backend envía ``value`` como string con JSON anidado y, en ocasiones, un
    ``;`` final. Devuelve siempre un ``dict``:
      - si ``raw_value`` es un string con JSON válido → el objeto decodificado;
      - si ya es un ``dict`` → se devuelve tal cual;
      - en cualquier otro caso (JSON inválido, tipo inesperado) → ``{}``.
    """
    if isinstance(raw_value, dict):
        return raw_value

    if not isinstance(raw_value, str):
        return {}

    cleaned = raw_value.strip()
    if cleaned.endswith(";"):
        cleaned = cleaned[:-1]

    try:
        parsed = json.loads(cleaned)
    except (ValueError, TypeError) as err:
        _LOGGER.warning(
            "[MySair MQTT] ⚠️ Error decodificando JSON anidado: %s -> %s...",
            err,
            raw_value[:120],
        )
        return {}

    return parsed if isinstance(parsed, dict) else {}


def _to_float(value):
    """Convierte a float; devuelve None si no es convertible o falta."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_str(value):
    return None if value is None else str(value)


def parse_mode(m):
    """Interpreta el campo ``m`` (modo, 0-5) del payload de estado.

    Semántica CONFIRMADA desde la app oficial (ver docs/protocol-findings.md):
      - par = calor, impar = frío
      - AC activo si m ∈ {0,1,4,5}; suelo radiante activo si m ∈ {2,3,4,5}

    Devuelve la tupla (mode_raw, is_heat, is_cool, is_ac, is_floor); todos los
    booleanos son None si ``m`` falta o no es numérico.
    """
    if m is None:
        return None, None, None, None, None
    mode_raw = str(m)
    try:
        n = int(mode_raw)
    except ValueError:
        return mode_raw, None, None, None, None
    is_heat = n % 2 == 0
    return mode_raw, is_heat, not is_heat, n in (0, 1, 4, 5), n in (2, 3, 4, 5)


def compute_mode_value(is_heat, is_ac, is_floor):
    """Calcula el valor de ``m`` a enviar por el comando ``mode`` dado el
    estado deseado (inverso de ``parse_mode``, F4 — control de suelo).

    Confirmado desde la app oficial (`docs/protocol-findings.md` §4):
    ``base``: AC=0, Suelo=2, AC+Suelo=4 (calor); ``+1`` si frío.

    Si ni AC ni suelo quedarían activos (combinación que la app nunca
    genera, ver `toggleRadiatingFloor`/`setModeHeat`), se fuerza AC=True
    para no enviar un ``m`` nunca visto en el bundle.
    # TODO(validar): comportamiento exacto de la app en ese caso límite no
    confirmado; no debería alcanzarse en uso normal (siempre queda al menos
    un medio activo).
    """
    if not is_ac and not is_floor:
        is_ac = True
    base = 4 if (is_ac and is_floor) else (2 if is_floor else 0)
    return str(base if is_heat else base + 1)


def parse_status_payload(payload):
    """Normaliza el payload de un mensaje ``status`` a ``{"ctl", "zones"}``.

    Semántica de los campos de zona (CONFIRMADA desde la app oficial, ver
    docs/protocol-findings.md):
      - ``e``  → ENCENDIDO: "0"=off, "1"=on, "2"=standby  (NO es el modo)
      - ``m``  → MODO 0-5: par=calor, impar=frío; {0,1,4,5}=AC, {2,3,4,5}=suelo
      - ``tr``/``tc``/``tmm``/``tmx``/``hum`` → temp actual/consigna/min/max/humedad
        (``hum``, no ``hm``: corregido tras confirmarlo con una captura real de
        producción el 2026-07-20 — la app internamente expone `this.hm`, pero
        el campo en el JSON de la zona es `hum`. Se mantiene `hm` como
        fallback por si alguna variante del backend lo envía así.)
      - capacidades: ``c``=permite calor, ``f``=permite frío, ``v``=fan, ``s``=suelo

    Cada zona en ``zones`` incluye: ``ctl``, ``zone_id``, ``zone_name``,
    ``temp_actual``, ``temp_target``, ``temp_min``, ``temp_max``, ``humidity``,
    ``power`` (e crudo), ``is_on``, ``is_standby``, ``mode_raw``, ``is_heat``,
    ``is_cool``, ``is_ac``, ``is_floor``, ``fan_mode`` y flags ``allow_*``.

    Validación (E2/E4): un ``payload`` que no sea ni siquiera un ``dict`` se
    **rechaza** devolviendo ``None`` (en vez de un dict "vacío" que de todas
    formas no hace nada aguas abajo). El resto de formas inesperadas (``ctl``
    ausente, ``t`` con una forma que no es una lista, una zona sin ``rf``) se
    degradan de forma segura como hasta ahora, pero ahora quedan
    **logueadas** para poder depurarlas — deliberadamente no se rechazan
    claves adicionales desconocidas del payload (permisivo ante campos
    nuevos del backend, ver `docs/known-unknowns.md`).
    """
    if not isinstance(payload, dict):
        _LOGGER.warning(
            "[MySair] status: payload no es un dict (%s), se rechaza el mensaje", type(payload).__name__
        )
        return None

    ctl_ref = payload.get("ctl")
    if ctl_ref is None:
        _LOGGER.warning("[MySair] status: payload sin 'ctl', el mensaje quedará sin destinatario")
    parsed_value = parse_status_value(payload.get("value", ""))

    t_list = parsed_value.get("t", [])
    if not isinstance(t_list, list):
        _LOGGER.warning(
            "[MySair] status: campo 't' con forma inesperada (%s), se ignora", type(t_list).__name__
        )
        t_list = []

    zone_states = []
    for t in t_list:
        if not isinstance(t, dict):
            continue
        if t.get("rf") is None:
            _LOGGER.warning("[MySair] status: zona sin 'rf' (zone_id), se generará sin identificador")
        power = _to_str(t.get("e", "0"))
        mode_raw, is_heat, is_cool, is_ac, is_floor = parse_mode(t.get("m"))
        zone_states.append(
            {
                "ctl": ctl_ref,
                "zone_id": t.get("rf"),
                "zone_name": t.get("n"),
                "temp_actual": _to_float(t.get("tr")),
                "temp_target": _to_float(t.get("tc")),
                "temp_min": _to_float(t.get("tmm")),
                "temp_max": _to_float(t.get("tmx")),
                "humidity": _to_float(t.get("hum", t.get("hm"))),
                "power": power,           # e crudo: "0"/"1"/"2"
                "is_on": power != "0",    # standby ("2") también cuenta como encendido
                "is_standby": power == "2",
                "mode_raw": mode_raw,     # m crudo: "0".."5"
                "is_heat": is_heat,
                "is_cool": is_cool,
                "is_ac": is_ac,
                "is_floor": is_floor,
                "fan_mode": _to_str(t.get("vv")),
                "allow_heat": _to_str(t.get("c")) == "1",
                "allow_cool": _to_str(t.get("f")) == "1",
                "allow_fan": _to_str(t.get("v")) == "1",
                "allow_floor": _to_str(t.get("s")) == "1",
            }
        )

    return {"ctl": ctl_ref, "zones": zone_states}


def parse_feedback_payload(payload):
    """Normaliza el payload del topic ``.../usr/{aws_mqtt_user}/feedback``.

    Confirmado desde la app oficial (ver docs/protocol-findings.md §8): el ACK
    de una instrucción se recibe como ``{orderId, ctl, ...}`` plano sobre el
    mismo objeto que entrega el wrapper MQTT (mismo shape que ``payload`` en
    ``mqtt_handler._on_message``). No hay captura real de producción que lo
    confirme (`known-unknowns` #23), así que además se prueba, como
    alternativa defensiva, la forma anidada de ``status`` (``value`` como
    string JSON) por si el backend envuelve también este topic así.

    Devuelve ``{"order_id", "ctl", "raw"}``; ``order_id``/``ctl`` son ``None``
    si no se encuentran en ninguna de las dos formas.

    Validación (E4): un ``payload`` que no sea un ``dict`` se rechaza
    devolviendo ``None``. Si es un dict pero no se encuentra ``orderId``/
    ``ctl`` en ninguna de las dos formas conocidas, se loguea (antes era
    silencioso) pero se sigue devolviendo el dict con ``None``s, ya que la
    forma general del mensaje sí se reconoció.
    """
    if not isinstance(payload, dict):
        _LOGGER.warning(
            "[MySair] feedback: payload no es un dict (%s), se rechaza el mensaje", type(payload).__name__
        )
        return None

    order_id = payload.get("orderId")
    ctl = payload.get("ctl")

    if order_id is None or ctl is None:
        nested = parse_status_value(payload.get("value", ""))
        if order_id is None:
            order_id = nested.get("orderId")
        if ctl is None:
            ctl = nested.get("ctl", payload.get("ctl"))

    if order_id is None and ctl is None:
        _LOGGER.warning("[MySair] feedback: no se encontró 'orderId' ni 'ctl' (ni plano ni anidado)")

    return {"order_id": order_id, "ctl": ctl, "raw": payload}
