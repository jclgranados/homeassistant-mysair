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


def parse_status_payload(payload):
    """Normaliza el payload de un mensaje ``status`` a ``{"ctl", "zones"}``.

    Cada zona en ``zones`` tiene las claves: ``ctl``, ``zone_id``, ``zone_name``,
    ``temp_actual``, ``temp_target``, ``temp_min``, ``temp_max`` y ``mode``.

    Nota sobre ``mode`` (campo ``e`` del payload): el mapeo asumido es
    0=off, 1=heat, 2=cool. Semántica pendiente de confirmar
    (ver docs/known-unknowns.md #2).
    """
    if not isinstance(payload, dict):
        return {"ctl": None, "zones": []}

    ctl_ref = payload.get("ctl")
    parsed_value = parse_status_value(payload.get("value", ""))

    zone_states = []
    for t in parsed_value.get("t", []):
        if not isinstance(t, dict):
            continue
        zone_states.append(
            {
                "ctl": ctl_ref,
                "zone_id": t.get("rf"),
                "zone_name": t.get("n"),
                "temp_actual": float(t.get("tr", 0.0)),
                "temp_target": float(t.get("tc", 0.0)),
                "temp_min": float(t.get("tmm", 0.0)),
                "temp_max": float(t.get("tmx", 0.0)),
                "mode": int(t.get("e", 0)),  # 0=off, 1=heat, 2=cool
            }
        )

    return {"ctl": ctl_ref, "zones": zone_states}
