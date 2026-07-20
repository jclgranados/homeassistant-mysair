# Seguridad y privacidad

> Análisis estático. No se han ejecutado peticiones reales. No se reproducen secretos.

---

## 1. Inventario de datos sensibles y su ubicación

| Dato | Dónde vive | Persistencia | Riesgo | Certeza |
|---|---|---|---|---|
| `email` | `entry.data["email"]` | Config entry (disco, `.storage/core.config_entries`) | Bajo | Confirmado |
| `password` **en claro** | `entry.data["password"]` | Config entry (disco) | 🔴 Alto | Confirmado (`config_flow.py:50`) |
| `access_token` / `refresh_token` | `entry.data` (nunca reutilizados) y `MySairAPI` en memoria | Config entry + memoria | 🟡 Medio | Confirmado (`config_flow.py:51-52`) |
| Credenciales AWS IoT (`aws_access_key_id`, `aws_secret_access_key`, `aws_security_token`) | `MySairAPI.aws_credentials` | Solo memoria | 🟡 Medio (temporales) | Confirmado (`api.py:121-128`) |
| URL MQTT firmada (contiene credencial + firma) | Variable local en `_run` | Solo memoria; **se loguea truncada a 120 chars** | 🟡 Medio | Confirmado (`mqtt_handler.py:131`) |

**No hay secretos hardcodeados en el repositorio.** Lo único fijo es el host público `https://api.mysair.es/v1` (`api.py:18`, no es secreto) y el fallback `web0077` para `app` (`api.py:252`, identificador de cliente, no secreto). **Confirmado.**

---

## 2. Riesgos por logging

| Log | Contenido potencialmente sensible | Severidad | Ubicación |
|---|---|---|---|
| `URL MQTT firmada [:120]` | Prefijo de la firma AWS (incluye `X-Amz-Credential`, access key parcial) | 🟡 Media | `mqtt_handler.py:131` |
| `Credenciales AWS obtenidas para usuario {aws_mqtt_user}` | Username MQTT (no secreto crítico) | Baja | `api.py:130` |
| `Enviando instrucción: {instruction}` (nivel INFO) | `app` (=aws_mqtt_user), refs; sin token | Baja | `api.py:197` |
| `Mensaje MQTT recibido [:200]` | Estado de zonas (datos personales de uso) | Baja | `mqtt_handler.py:191` |
| `Login {email}` | Email del usuario | Baja | `api.py:31` |

**Riesgo positivo:** en ningún log se imprime `password`, `access_token`, `aws_secret_access_key` ni `aws_security_token` completos. **Confirmado.**

**Recomendaciones de redacción:**
- No loguear ninguna parte de la URL firmada (ni truncada). Loguear solo el `host`.
- Bajar a `DEBUG` los logs INFO con contenido operativo.
- Considerar un filtro de logging que enmascare patrones `X-Amz-*` y `Bearer <...>`.

---

## 3. Almacenamiento de credenciales — recomendaciones

1. 🔴 **No guardar `password` en claro.** Opciones:
   - Guardar solo `refresh_token` y usar `PUT /user/refreshtokens` para renovar (requiere que el refresh token no caduque pronto — **Desconocido**).
   - Si hay que conservar la contraseña para re-login, documentarlo y asumir que HA cifra `.storage` solo si el disco está cifrado (no lo hace por sí mismo).
2. 🔴 **Eliminar `access_token`/`refresh_token` de `entry.data`** si no se reutilizan (hoy no se usan): son ruido que caduca.
3. 🟡 Implementar **reauth flow** para rotar contraseña sin borrar la entrada.
4. 🟡 Tratar las credenciales AWS como **efímeras**: refrescarlas proactivamente antes de cada reconexión MQTT (hoy se reutilizan hasta fallar — ver `mqtt_handler.py:110`).

---

## 4. Riesgos de la ingeniería inversa / dependencia de servicio externo

| Riesgo | Descripción | Severidad |
|---|---|---|
| API no documentada | `api.mysair.es/v1` puede cambiar rutas, campos o autenticación sin aviso → rotura silenciosa | 🟡 Media |
| Cambios en formato MQTT | El parsing es frágil (split por bytes nulos, extracción `{...}`) → un cambio menor de formato rompe el estado | 🟡 Media |
| `client_id` compartido | Usar el mismo `aws_mqtt_user` que la app oficial puede provocar expulsiones mutuas en AWS IoT | 🔎 Requiere investigación |
| Términos de servicio | Uso no oficial de la API/infra de MySair; posible incumplimiento de ToS | 🔎 Legal, fuera de alcance técnico |
| Rate limiting | El refresco cada 60 s por instalación podría activar límites del backend | 🔎 Desconocido |
| Firma con reloj local | `datetime.utcnow()` — si el reloj del host está desfasado, la firma SigV4 falla | 🟡 Media |

---

## 5. Superficie de red

- Salientes únicamente: HTTPS a `api.mysair.es` y WSS a `*.iot.<region>.amazonaws.com`. **Confirmado.**
- No abre puertos entrantes.
- Verificación TLS: `requests` y `websocket-client` verifican certificados por defecto; el código **no** desactiva la verificación. ✅ **Confirmado** (no hay `verify=False` ni `sslopt` inseguro).

---

## 6. Checklist de seguridad para futuras sesiones

- [ ] Nunca imprimir en logs `password`, tokens, `aws_secret_access_key`, `aws_security_token` ni URLs firmadas completas.
- [ ] No commitear ficheros de captura (`.har`, dumps MQTT) con credenciales reales.
- [ ] Mantener `.gitignore` cubriendo `secrets.*`, `*.har`, `.env`.
- [ ] Al añadir `diagnostics.py`, usar `async_redact_data` para ocultar credenciales.
- [ ] No ejecutar comandos contra instalaciones reales durante el desarrollo (ver `CLAUDE.md`).
- [ ] Revisar que cualquier nuevo log de payload MQTT no exponga datos personales de forma innecesaria.

---

## 7. Estado actual del repositorio respecto a secretos

**Confirmado:** el repositorio versionado **no contiene** credenciales, tokens ni capturas. `.gitignore` solo excluye `__pycache__`. Recomendación: ampliarlo (ver checklist) como medida preventiva antes de que alguien añada fixtures o capturas reales.
