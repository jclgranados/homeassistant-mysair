import asyncio
import json
import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .api import MySairAPI
from .mqtt_handler import MySairMQTTClient
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["climate", "sensor", "switch"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Configura la integración MySair."""
    loop = asyncio.get_running_loop()

    # Asegurar que paho.mqtt se carga fuera del event loop
    await loop.run_in_executor(None, lambda: __import__("paho.mqtt.client"))

    email = entry.data.get("email")
    password = entry.data.get("password")

    _LOGGER.info(f"[MySair] 🔐 Autenticando usuario {email}")
    api = MySairAPI(email, password)

    # --- LOGIN ---
    await hass.async_add_executor_job(api.login)

    # --- ESTRUCTURA: Locations → Installations → Devices ---
    locations = await hass.async_add_executor_job(api.get_locations)
    if not locations:
        _LOGGER.error("[MySair] ❌ No se encontraron ubicaciones.")
        return False

    first_loc = locations[0]
    location_id = first_loc["id"]
    installations = await hass.async_add_executor_job(api.get_installations, location_id)
    if not installations:
        _LOGGER.error("[MySair] ❌ No se encontraron instalaciones en la ubicación.")
        return False

    _LOGGER.info(f"[MySair] 🏠 Instalaciones detectadas: {[i['reference'] for i in installations]}")

    all_devices = {}
    installation_refs = []
    for inst in installations:
        ref = inst["reference"]
        installation_refs.append(ref)
        devices = await hass.async_add_executor_job(api.get_devices, ref)
        all_devices[ref] = devices
        _LOGGER.info(f"[MySair] 📟 Instalación {ref}: {len(devices)} termostatos encontrados")

    # Guardar datos en memoria global
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "devices": all_devices,
        "installations": installation_refs,
        "mqtt": None,
    }

    # --- CALLBACK PARA MQTT (con parseo de mensajes status) ---
    def mqtt_message_callback(data):
        """Procesa mensajes entrantes desde AWS IoT."""
        try:
            topic = data.get("topic", "")
            payload = data.get("payload", {})
            _LOGGER.debug(f"[MySair MQTT] 📩 {topic} -> {payload}")

            # Si el mensaje es de tipo "status", lo parseamos
            if topic.endswith("/status"):
                try:
                    ctl_ref = payload.get("ctl")
                    raw_value = payload.get("value", "")
                    parsed_value = {}
                    if isinstance(raw_value, str):
                        try:
                            # Limpieza: eliminar punto y coma o basura final
                            cleaned = raw_value.strip()
                            if cleaned.endswith(";"):
                                cleaned = cleaned[:-1]
                            # Cargar JSON válido
                            parsed_value = json.loads(cleaned)
                        except Exception as e:
                            _LOGGER.warning(f"[MySair MQTT] ⚠️ Error decodificando JSON anidado: {e} -> {raw_value[:120]}...")
                            parsed_value = {}
                    else:
                        parsed_value = raw_value
#                    parsed_value = json.loads(raw_value) if isinstance(raw_value, str) else raw_value

                    thermostats = parsed_value.get("t", [])
                    zone_states = []

                    for t in thermostats:
                        zone_states.append({
                            "ctl": ctl_ref,
                            "zone_id": t.get("rf"),
                            "zone_name": t.get("n"),
                            "temp_actual": float(t.get("tr", 0.0)),
                            "temp_target": float(t.get("tc", 0.0)),
                            "temp_min": float(t.get("tmm", 0.0)),
                            "temp_max": float(t.get("tmx", 0.0)),
                            "mode": int(t.get("e", 0)),  # 0=off, 1=heat, 2=cool
                        })

                    parsed_data = {
                        "ctl": ctl_ref,
                        "zones": zone_states
                    }

                    # Enviar evento con datos parseados
                    hass.loop.call_soon_threadsafe(
                        hass.bus.async_fire,
                        f"{DOMAIN}_update",
                        {"topic": topic, "data": parsed_data},
                    )

                    _LOGGER.debug(f"[MySair MQTT] 🧩 Estado parseado: {parsed_data}")

                except Exception as e:
                    _LOGGER.warning(f"[MySair MQTT] ⚠️ Error al parsear mensaje de estado: {e}")

            else:
                # Otros mensajes (no status)
                hass.loop.call_soon_threadsafe(
                    hass.bus.async_fire,
                    f"{DOMAIN}_update",
                    {"topic": topic, "data": payload},
                )

        except Exception as e:
            _LOGGER.error(f"[MySair MQTT] ❌ Error en callback: {e}")

    # --- CLIENTE MQTT ---
    mqtt_client = MySairMQTTClient(api, installation_refs, mqtt_message_callback)
    hass.data[DOMAIN][entry.entry_id]["mqtt"] = mqtt_client

    # Lanzar el hilo MQTT sin bloquear el loop
    await hass.async_add_executor_job(mqtt_client.start)

    # --- PLATAFORMAS ---
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _LOGGER.info("[MySair] ✅ Plataformas cargadas correctamente")

    # --- REFRESCO AUTOMÁTICO DE STATUS ---
    async def refresh_status_periodic():
        """Envía cada 5 minutos una instrucción 'status' a todas las instalaciones."""
        while True:
            try:
                for ref in installation_refs:
                    instruction = [{
                        "sender": "WEB",
                        "ctl": ref,
                        "app": api.aws_credentials.get("aws_mqtt_user", "web0077") if api.aws_credentials else "web0077",
                        "device": "",
                        "command": "status",
                        "value": "sync",
                    }]
                    await hass.async_add_executor_job(api.send_instruction, instruction)
                    _LOGGER.debug(f"[MySair] 🔁 Solicitud de estado enviada a instalación {ref}")
            except Exception as e:
                _LOGGER.warning(f"[MySair] ⚠️ Error al enviar instrucción de estado: {e}")
            await asyncio.sleep(60)  # 5 minutos

    # Lanzar la tarea periódica
    hass.loop.create_task(refresh_status_periodic())

    # --- FINALIZADOR LIMPIO ---
    async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
        _LOGGER.info("[MySair] 🔌 Deteniendo integración y cerrando sesiones...")
        data = hass.data[DOMAIN].pop(entry.entry_id, None)
        if data:
            mqtt_client = data.get("mqtt")
            if mqtt_client:
                await hass.async_add_executor_job(mqtt_client.stop)
            api = data.get("api")
            if api:
                await hass.async_add_executor_job(getattr, api, "close", lambda: None)
        await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
        return True

    entry.async_on_unload(entry.add_update_listener(async_unload_entry))
    return True

