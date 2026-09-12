"""Información de dispositivo compartida por las entidades de una zona.

Las 7 entidades de una zona (climate, 4 sensores, 2 switches) pertenecen al
mismo dispositivo y repetían el mismo bloque ``device_info`` palabra por
palabra. Además, desde que las entidades usan ``has_entity_name`` el nombre
del dispositivo dejó de ser decorativo: Home Assistant lo antepone al nombre
de cada entidad para componer tanto el nombre visible como el ``entity_id``,
así que tiene que ser el nombre de la zona ("Salón") y no un identificador
interno.
"""

from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN


def zone_device_info(inst_ref: str, device_id: str, zone_name: str) -> DeviceInfo:
    """Dispositivo que agrupa todas las entidades de una zona.

    ``identifiers`` se mantiene igual que antes
    (``{(DOMAIN, f"{inst_ref}_{device_id}")}``): es la clave con la que
    Home Assistant reconoce dispositivos ya registrados, y también la que
    usa ``_cleanup_stale_zone_devices`` (``__init__.py``) para detectar
    zonas que han desaparecido de la cuenta.
    """
    return DeviceInfo(
        identifiers={(DOMAIN, f"{inst_ref}_{device_id}")},
        name=zone_name,
        manufacturer="MySair",
        model="Zonificador de climatización",
    )


def account_device_info(entry_id: str) -> DeviceInfo:
    """Dispositivo "de cuenta", que agrupa lo que no pertenece a una zona.

    Hoy solo el sensor de conexión MQTT. Se identifica por ``entry_id``, no
    por una referencia de instalación, y ``_cleanup_stale_zone_devices`` lo
    reconoce por eso para no borrarlo nunca como si fuera una zona huérfana.
    """
    return DeviceInfo(
        identifiers={(DOMAIN, entry_id)},
        name="MySair",
        manufacturer="MySair",
        model="Integración",
    )
