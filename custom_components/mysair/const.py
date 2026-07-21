DOMAIN = "mysair"

# Tiempo de espera de confirmación (ACK) de un comando vía topic feedback
# antes de avisar en logs. Valor confirmado desde la app oficial
# (VUE_APP_OUTSERVICE_MILISECOND=5000, ver docs/protocol-findings.md §6b).
FEEDBACK_TIMEOUT_SECONDS = 5

# Antigüedad máxima de un status MQTT antes de marcar la entidad como no
# disponible (C5). 3x el intervalo del refresco periódico de respaldo (120 s,
# __init__.py) para no dar falsos "no disponible" por jitter normal.
MQTT_STALE_AFTER_SECONDS = 360

# Atributos comunes
ATTR_TARGET_TEMP = "target_temperature"
ATTR_CURRENT_TEMP = "current_temperature"
ATTR_MODE = "mode"
ATTR_HVAC_STATE = "hvac_action"

# Intervalos por defecto
SCAN_INTERVAL = 60  # segundos

# Servicio mysair.stop_installation (F5)
SERVICE_STOP_INSTALLATION = "stop_installation"
ATTR_INSTALLATION_REF = "installation_ref"
