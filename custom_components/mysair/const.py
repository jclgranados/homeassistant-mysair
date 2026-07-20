DOMAIN = "mysair"

# Tiempo de espera de confirmación (ACK) de un comando vía topic feedback
# antes de avisar en logs. Valor confirmado desde la app oficial
# (VUE_APP_OUTSERVICE_MILISECOND=5000, ver docs/protocol-findings.md §6b).
FEEDBACK_TIMEOUT_SECONDS = 5

# Atributos comunes
ATTR_TARGET_TEMP = "target_temperature"
ATTR_CURRENT_TEMP = "current_temperature"
ATTR_MODE = "mode"
ATTR_HVAC_STATE = "hvac_action"

# Modos compatibles
HVAC_MODES = ["off", "heat", "cool", "auto"]

# Intervalos por defecto
SCAN_INTERVAL = 60  # segundos

