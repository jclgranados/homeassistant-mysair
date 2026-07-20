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


def parse_status_payload(payload):
    """Normaliza el payload de un mensaje ``status`` a ``{"ctl", "zones"}``.

    Semántica de los campos de zona (CONFIRMADA desde la app oficial, ver
    docs/protocol-findings.md):
      - ``e``  → ENCENDIDO: "0"=off, "1"=on, "2"=standby  (NO es el modo)
      - ``m``  → MODO 0-5: par=calor, impar=frío; {0,1,4,5}=AC, {2,3,4,5}=suelo
      - ``tr``/``tc``/``tmm``/``tmx``/``hm`` → temp actual/consigna/min/max/humedad
      - capacidades: ``c``=permite calor, ``f``=permite frío, ``v``=fan, ``s``=suelo

    Cada zona en ``zones`` incluye: ``ctl``, ``zone_id``, ``zone_name``,
    ``temp_actual``, ``temp_target``, ``temp_min``, ``temp_max``, ``humidity``,
    ``power`` (e crudo), ``is_on``, ``is_standby``, ``mode_raw``, ``is_heat``,
    ``is_cool``, ``is_ac``, ``is_floor``, ``fan_mode`` y flags ``allow_*``.
    """
    if not isinstance(payload, dict):
        return {"ctl": None, "zones": []}

    ctl_ref = payload.get("ctl")
    parsed_value = parse_status_value(payload.get("value", ""))

    zone_states = []
    for t in parsed_value.get("t", []):
        if not isinstance(t, dict):
            continue
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
                "humidity": _to_float(t.get("hm")),
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
