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
| `sv` | estado de suelo actual | str |
| `pl` | principal | flag |
| Capacidades | `c`=permite calor, `f`=permite frío, `v`=fan, `s`=suelo, `tz`=timer, `hp`=programas | "1"/"0" |
| `v` (instalación) | versión | — |

## 6. Suscripción MQTT

```js
subscribe(e){ ... this.$emitInstance("suscribe", e, `ctl/${e}/#`) }
```
Coincide con el topic `pro/v1/get/ctl/{ref}/#` de la integración (con el prefijo `pro/v1/get/`).

---

## 7. Impacto en la integración (correcciones derivadas)

| Área | Estado actual | Corrección confirmada |
|---|---|---|
| Comando `mode` heat/cool (solo-aire) | `0`=calor, `1`=frío | ✅ Ya correcto |
| Parser de estado: modo | Lee `e` como modo (0=off,1=heat,2=cool) | 🔴 Debe leer **on/off de `e`** y **calor/frío de la paridad de `m`** |
| `switch.turn_on` | Envía `mode:"1"` (fuerza frío) | 🔴 Encender debe preservar/usar calor (m par) o el modo actual |
| `power` off | `value:"0"` | ✅ Ya correcto |
| Campos `tr/tc/tmm/tmx` | Correctos | ✅ |
| Capacidades (`c/f/v/s`) y humedad (`hm`) | No usados | 🟢 Oportunidad: exponer disponibilidad heat/cool, fan, humedad |
| Comandos `fanspeed/temporizer/stop/programs` | No implementados | 🟢 Oportunidad de nuevas funcionalidades |
