# Hallazgos del protocolo desde la app oficial

> Fuente: bundle JavaScript de la app web MySair `https://app.mysair.es/js/app.09acea34.js`
> (asset estático público; no se interactúa con API de comandos, MQTT ni dispositivos).
> Nivel de certeza: **Confirmado** — extraído directamente de la lógica de la app.
> Los fragmentos son código de la app (minificado, sin secretos). Fecha de análisis: 2026-07-19.

---

## 1. Sobre / envoltorio de la instrucción

```js
_generateInstruction(e,t,i,a){
  return { sender:"WEB", ctl:e, app:this.$session.getClientId(), device:t, command:i, value:a }
}
```
- `app` = `session.getClientId()` (equivalente al `aws_mqtt_user`).
- Idéntico a lo que envía la integración.

## 2. Catálogo de comandos (mixin de instrucciones)

```js
setPower(e,t,i,...){ _sendInstruction(e,t,"power",i,...) }        // apagar: value "0"
setMode(e,t,i,...){ _sendInstruction(e,t,"mode",i,...) }          // encender / fijar modo
setTemp(e,t,i,...){ _sendInstruction(e,t,"temp",""+i,...) }        // consigna (string)
setFanspeed(e,t,i,...){ _sendInstruction(e,t,"fanspeed",""+i,...) }
setTemporizer(e,t,i,...){ _sendInstruction(e,t,"temporizer",i,...) }
stopInstallation(e,t,...){ _sendInstruction(e,t,"stop","1",...) }
getPrograms(e,t,...){ _sendInstruction(e,t,"programs","",...) }
getStatus(e,...){ $api.instruction(_generateInstruction(e,"","status","sync")) }
```

| `command` | `value` | Finalidad |
|---|---|---|
| `power` | `"0"` | Apagar (único uso observado del comando power) |
| `mode` | `{mode:"0".."5", temperature:"<tc>"}` | Encender / fijar modo |
| `temp` | `"<temp>"` | Consigna |
| `fanspeed` | `"<n>"` | Velocidad de ventilador |
| `temporizer` | `<timer>` | Temporizador |
| `stop` | `"1"` | Parar instalación |
| `status` | `"sync"` | Solicitar estado |
| `programs` | `""` | Leer programas |

## 3. Encendido / apagado

```js
setModeHeat:function(e,t){                       // e = AC on/off, t = Suelo on/off
  if(!e&&!t) return this.setPower(installation_ref, reference, "0", ...);  // ambos off -> power "0"
  this.status.setMode(this.status.isModeHeat(), e, t);
  this.status.setPower(!0);
  this.setMode(installation_ref, reference, {mode:this.status.getMode(), temperature:this.status.getOrder()}, ...)
}
```
- **Apagar** = `command:"power", value:"0"`.
- **Encender** = `command:"mode"` con el `m` deseado. **No existe `power:"1"`**.

## 4. Modelo de estado por zona (clase `te`)

```js
isOn()      { return "0" != this.e }              // e: "0"=off, "1"=on, "2"=standby
isStanby()  { return "2" == this.e }
isModeAC()  { return this.isOn() && ["0","1","4","5"].includes(this.m) }
isModeFloor(){ return this.isOn() && ["2","3","4","5"].includes(this.m) }
getMode(){return this.m}  getOrder(){return this.tc}  getTemp(){return this.tr}
getTempMin(){return this.tmm}  getTempMax(){return this.tmx}  getHumidity(){return this.hm}
getFanMode(){return this.vv}  getTimer(){return this.tzv}
allowHeat(){return "1"==this.c}  allowCool(){return "1"==this.f}
allowFan(){return "1"==this.v}   allowFloor(){return "1"==this.s}
allowTimer(){return "1"==this.tz}  allowPrograms(){return "1"==this.hp}

setMode(e,t,i){ let a=null;                        // e=esCalor, t=AC, i=Suelo
  t&&!i&&(a=0); !t&&i&&(a=2); t&&i&&(a=4);         // AC=0, Suelo=2, AC+Suelo=4
  e||(a+=1);                                       // +1 si NO es calor (=frío)
  this.m=""+a }
setPower(e){ this.e = e?"1":"0" }
```

Nivel de instalación (`ae`): `this.heat = ["0","2","4"].includes(t.m)` → confirma **par=calor**.

### Tabla del campo `m` (modo)

| `m` | AC | Suelo | Temp |
|---|:--:|:--:|---|
| `0` | ✓ | | Calor |
| `1` | ✓ | | Frío |
| `2` | | ✓ | Calor |
| `3` | | ✓ | Frío |
| `4` | ✓ | ✓ | Calor |
| `5` | ✓ | ✓ | Frío |

**Par = calor, impar = frío.**

## 5. Campos del payload de zona (mapeo `_validateInstallation`)

```js
t = JSON.parse(t.value.slice(0,-1))               // confirma el ';' final que se recorta
devices: t.t.map(e=>({
  reference:e.rf, name:e.n, principal:e.pl, floor:e.s,
  cold:e.f, hot:e.c, fan:e.v, timer:e.tz, programming:e.hp,
  temperature_max:e.tmx, temperature_min:e.tmm
}))
```

| Campo | Significado | Tipo |
|---|---|---|
| `rf` | referencia de zona | str |
| `n` | nombre | str |
| `e` | **encendido**: 0=off, 1=on, 2=standby | str |
| `m` | **modo** 0-5 (ver §4) | str |
| `tr` | temperatura actual | num |
| `tc` | consigna (order) | num |
| `tmm` / `tmx` | temp mín / máx | num |
| `hm` | humedad | num |
| `vv` | modo/velocidad de ventilador actual | str |
| `tzv` | valor de temporizador actual | str |
| `sv` | **suelo radiante encendido/apagado**: "0"/"1" (distinto de la capacidad `s`) | str |
| `pl` | principal | flag |
| Capacidades | `c`=permite calor, `f`=permite frío, `v`=fan, `s`=suelo, `tz`=timer, `hp`=programas | "1"/"0" |
| `v` (instalación) | versión | — |

**Confirmación de `sv`** (2026-07-21, re-fetch de `app.09acea34.js`, mismo hash que el análisis original): la fila
original de esta tabla no citaba un getter concreto, y una revisión posterior (Tarea 22) no lo encontró y lo dejó
como incógnita. Al repetir la búsqueda se localizó:
```js
setFloor(e){this.sv=e?"1":"0"}
// ...
toggleRadiatingFloor:function(e){this.status.setFloor(e),this.setModeHeat(this.status.isModeAC(),e)}
```
`setFloor` actúa sobre `this.status` (el mismo objeto en vivo donde residen `e`/`m`/`tc`), confirmando que `sv` es
parte del estado de zona real, no solo de configuración estática. Ver `docs/known-unknowns.md` #26.

## 6. Suscripción MQTT

```js
subscribe(e){ ... this.$emitInstance("suscribe", e, `ctl/${e}/#`) }
```
Coincide con el topic `pro/v1/get/ctl/{ref}/#` de la integración (con el prefijo `pro/v1/get/`).

---

## 6b. Conexión MQTT, topics y expiración (CONFIRMADO)

### Cliente MQTT y clientId
```js
Ha=e=>Fa.device({
  accessKeyId:e.accessKeyId, secretKey:e.secretKey, sessionToken:e.sessionToken,
  clientId:`mqtt-client_${e.accessKeyId}_${Date.now()}`,   // ÚNICO por conexión
  protocol:"wss", host:e.host
})
```
- El `clientId` MQTT es **único por conexión** (`mqtt-client_<accessKeyId>_<timestamp>`), **no** el `aws_mqtt_user`.
- `getClientId()` = `aws_mqtt_user` se usa solo como campo `app` de las instrucciones y en el topic de feedback.

### Estructura de topics
```js
subscribe(e){ e=`${this._basePath}get/${e}`; ... }          // suscripción
publish(e,t){ e=`${this._basePath}set/${e}`; ... }           // publicación (la app usa HTTP para comandos)
processTopic(e){ var t=e.split("/"); return {env:t[0],version:t[1],method:t[2],type:t[3],device:t[4],property:t.slice(5).join("/")} }
```
- `_basePath` = `aws_base_topic` (campo de las credenciales) = `pro/v1/`.
- Estructura: `env/version/method/type/device/property` → p. ej. `pro/v1/get/ctl/{ref}/status`.
- La integración se suscribe a `pro/v1/get/ctl/{ref}/#` y recibe `.../status`. **Coincide.**
- Existe además `pro/v1/get/usr/{aws_mqtt_user}/feedback` (ack de instrucciones con `orderId`); la app lo usa para correlacionar comando→respuesta. La integración no lo usa.

### Expiración y refresco (session)
```js
getExpirationTime(){ return 1e3*expires_at - now }          // token HTTP
getMqttExpirationTime(){ return 1e3*aws_expires_at - now }  // credenciales AWS
getAwsCredential(){ return {host:aws_mqtt_host, basePath:aws_base_topic, accessKeyId, secretKey, sessionToken, clientId:aws_mqtt_user} }
// controlMqtt: setTimeout(refreshAwsCredentials, getMqttExpirationTime()) → refresca justo antes de expirar y reconecta
```
- Las credenciales AWS incluyen **`aws_expires_at`** (unix s) y **`aws_base_topic`**; el login incluye **`expires_at`**.
- La app **refresca proactivamente** las credenciales antes de `aws_expires_at`.

Config del bundle: `VUE_APP_API_DOMAIN="https://api.mysair.es"`, `VUE_APP_OUTSERVICE_MILISECOND="5000"`.

## 7. Impacto en la integración (correcciones derivadas)

| Área | Estado actual | Corrección confirmada |
|---|---|---|
| Comando `mode` heat/cool (solo-aire) | `0`=calor, `1`=frío | ✅ Ya correcto |
| Parser de estado: modo | Leía `e` como modo | ✅ Corregido (A5): on/off de `e`, calor/frío por paridad de `m` |
| `switch.turn_on` | Enviaba `mode:"1"` (forzaba frío) | ✅ Corregido (A5): preserva último modo, por defecto calor |
| `power` off | `value:"0"` | ✅ Ya correcto |
| Campos `tr/tc/tmm/tmx` | Correctos | ✅ |
| **`client_id` MQTT** | Usa `aws_mqtt_user` (colisiona con la app → expulsiones) | 🔴 Debe ser único por conexión: `mqtt-client_{accessKeyId}_{ts}` |
| **Expiración credenciales AWS** | Reutiliza hasta fallar | 🔴 Leer `aws_expires_at` y refrescar antes de expirar (y en cada reconexión) |
| **Base del topic** | Hardcodea `pro/v1/get/` | 🟡 Debería venir de `aws_base_topic` (fallback al valor actual) |
| Token HTTP `expires_at` | Refresca solo ante 401 | 🟡 Oportunidad: refresco proactivo |
| Topic de feedback `usr/{user}/feedback` | No usado | ✅ Consumido: suscripción + evento `mysair_feedback` + log de confirmación/timeout por entidad (ver §8) |
| Capacidades `c`/`f` (calor/frío) y humedad (`hm`) | Parseadas, sin entidad | ✅ Expuestas: `climate.hvac_modes` dinámico según `allow_heat`/`allow_cool`, sensor de humedad por zona |
| Capacidades `v`/`s` (fan/suelo) | Parseadas, sin entidad | 🟢 Oportunidad: exponer fan/suelo (no implementado — requiere entender los comandos `fanspeed`) |
| `tmm`/`tmx` en `climate.min_temp`/`max_temp` | Fijos en 10/30 | ✅ Corregido (C8): se actualizan desde el status MQTT por zona |
| Comandos `fanspeed/temporizer/stop/programs` | No implementados | 🟢 Oportunidad de nuevas funcionalidades |

---

## 8. Confirmación de comandos: `orderId` y topic `feedback` (CONFIRMADO)

```js
// POST /send/instruction devuelve el orderId en la respuesta:
this.$api.instruction(this._generateInstruction(e,t,i,a),
  e=>this.$onceOutInstance("reciveInstruction_"+e.entity.value[0].orderId, ...))

// Suscripción al topic de feedback (una vez, con el clientId de sesión):
this.$mqtt.subscribe(`usr/${this.$session.getClientId()}/feedback`,
  e=>{this.$emitInstance("reciveInstruction_"+e.orderId,e)})
// (subscribe() antepone `${basePath}get/` → pro/v1/get/usr/{aws_mqtt_user}/feedback)
```

- La respuesta de `POST /send/instruction` incluye `entity.value[0].orderId` (confirmado; antes solo se leían `msg`/`error`).
- El ACK llega por MQTT en el topic `pro/v1/get/usr/{aws_mqtt_user}/feedback`, como un objeto con `orderId` (y `ctl`, usado por la app para encadenar con `reciveStatus_{ctl}`) **directamente sobre el objeto que entrega el wrapper MQTT** — sin envoltorio `value` de string JSON como en `status`.
- **No confirmado con captura real de producción** (`known-unknowns.md` #23): se implementó de forma defensiva (`status_parser.parse_feedback_payload` prueba primero la forma plana y cae a una forma anidada tipo `status` como fallback) para no romper si el backend envuelve este topic de otra manera.
- `VUE_APP_OUTSERVICE_MILISECOND="5000"` (config del bundle) es el timeout que usa la propia app para dar un comando por perdido — reutilizado tal cual como `FEEDBACK_TIMEOUT_SECONDS` en la integración.
- **Implementado:** suscripción al topic (`mqtt_handler.build_feedback_topic`), evento `mysair_feedback` en el bus (`__init__.py`), y en `climate.py`/`switch.py` (vía `command_feedback.CommandFeedbackMixin`) log de confirmación si llega el ACK con el `orderId` esperado, o log de aviso si no llega en 5 s. **No se revierte el estado optimista todavía** — eso queda pendiente de validar la forma real del payload en producción (ver `execution-plan.md` Tarea 16).

---

## 9. Velocidad de ventilador: significado de `vv`/`fanspeed` (CONFIRMADO)

```js
// Componente REAL de una instalación (no la página de demo/storybook de
// componentes UI, que usa datos ficticios de ejemplo — ver más abajo):
data(){return{type:"device",
  fanGroups:[{key:"auto",values:{4:"A"}},{key:"manual",values:{1:"1",2:"2",3:"3"}}],
  ...}}

hasFanMode(){return"0"!=this.vv}
getFanMode(){return this.vv}

// Click en el icono principal del ventilador (sin elegir grupo):
updateFanMode:function(e){
  this.status.setFanMode(e),
  this.setFanspeed(this.installation_ref,this.reference,e,e=>dd(e))
}
// onClick del icono principal (toggle): e.updateFanMode(e.status.hasFanMode()?"0":"4")
```

| `vv` | Significado |
|---|---|
| `"0"` | Sin modo de ventilador (`hasFanMode()` → `false`) |
| `"1"` / `"2"` / `"3"` | Velocidad manual 1 / 2 / 3 |
| `"4"` | Automático (mostrado como "A" en la UI) |

**⚠️ Trampa encontrada durante la investigación:** una página de demo/storybook de componentes UI en el mismo bundle define un `ventilationGroups:[{key:"",values:["A"]},{key:"manual",values:["1","2","3"]}]` con datos de ejemplo **inventados para mostrar el componente visualmente**, no ligados a ningún `vv` real. Una primera lectura superficial de esa página llevó a anotar esto como "pista sin confirmar" en `known-unknowns.md` #24 — la confirmación real vino de encontrar el componente de instalación de verdad (arriba), que sí liga `fanGroups` directamente a `this.vv` vía `getFanMode()`/`hasFanMode()`. Lección: en bundles con páginas de demo de componentes, verificar siempre que el código citado pertenece al flujo real de datos (aquí: el objeto `status`/`te`, el mismo de `docs/protocol-findings.md §4`), no a una demo aislada con valores de relleno.

- **Comando:** `command:"fanspeed"`, `value:""+i` (string del valor de `vv` deseado: `"0"`, `"1"`, `"2"`, `"3"` o `"4"`).
- **Capacidad:** solo se muestra el control si `allowFan()` (`"1"==this.v`) — ya parseado como `allow_fan` en `status_parser.py`.
- **Implementado:** `climate.py` expone `fan_mode`/`fan_modes` (HA `ClimateEntityFeature.FAN_MODE`) mapeando `"1"/"2"/"3"` tal cual y `"4"`↔`"auto"`; `async_set_fan_mode` envía `fanspeed` vía `api.send_zone_command`.
