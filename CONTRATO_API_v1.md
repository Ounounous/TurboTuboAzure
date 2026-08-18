# Contrato API v1 — TurboTubo ↔ motor de campañas

Versión 1.0 · 2026-08-15 · Fase 1 del plan de integración

Este documento es el contrato entre **TurboTubo** (dueño del deudor, traduce a su árbol de
cartera) y **cualquier motor de campañas externo** (envía mensajes, reporta si llegaron o no).
Es genérico a propósito: no menciona a "cobranza-saas" ni a ningún proveedor. Cualquier motor de
campañas que hable este vocabulario puede conectarse a TurboTubo sin que TurboTubo sepa nada de
su implementación interna.

Vive versionado en ambos repos:
- `TurboTuboAzure/CONTRATO_API_v1.md` (este archivo — fuente de verdad, TurboTubo es dueño del vocabulario de carteras)
- `cobranza-saas/CONTRATO_API_v1.md` (copia; cualquier cambio se sincroniza a mano hasta que exista CI cruzado)

Un motor de campañas **no puede** producir resultados que requieren conversación (`PROMESA DE
PAGO`, `CESANTE`, `DESCONOCE DEUDA`...) — eso exige un humano hablando con el deudor. Solo puede
reportar **si el mensaje llegó o no**. El vocabulario corto de abajo es deliberadamente chico: 8
eventos cubren cualquier canal de envío masivo (SMS, email, WhatsApp, carta, IVR).

## 1. Los tres mensajes

Tres formas de JSON, sin más. No hay un cuarto mensaje en v1.

### 1.1 Audiencia — `TurboTubo → motor`

TurboTubo entrega la lista de deudores a contactar. Es de solo lectura: el motor guarda estos
datos en su propio storage operativo, nunca construye un "Contacto maestro" ni un historial
propio — ese historial ya existe en TurboTubo como `Action` (ver decisión #2 del plan).

```json
{
  "tipo": "audiencia",
  "cartera": "galgo",
  "subcartera_id": 12,
  "generado_at": "2026-08-15T14:30:00Z",
  "objetivos": [
    {
      "op": "GAL-0001",
      "target": "principal",
      "canal": "sms",
      "destino": "+56911110001",
      "nombre": "Ana Torres",
      "saldo_insoluto": 850000,
      "cuotas_atrasadas": 3
    }
  ]
}
```

Campos:

| Campo | Tipo | Notas |
|---|---|---|
| `cartera` | string | `galgo` \| `tanner` \| `nuevo_capital` — clave para elegir la tabla de mapeo (sección 2) |
| `subcartera_id` | int | id de `Subcartera` en TurboTubo, para que el evento de vuelta (sección 1.3) sepa a qué lead volver |
| `objetivos[].op` | string | identificador estable del lead (`Lead.op`). El motor lo usa como clave, nunca el id interno de TurboTubo |
| `objetivos[].target` | string | `principal` \| `aval` — a quién se le manda el mensaje |
| `objetivos[].canal` | string | `sms` \| `email` \| `whatsapp` \| `carta` \| `ivr` |
| `objetivos[].destino` | string | teléfono o email según `canal` — ya filtrado por TurboTubo a estado `active` (nunca `blacklisted`/`non-existent`/`out of service`) |
| `nombre`, `saldo_insoluto`, `cuotas_atrasadas` | — | contexto para personalizar el mensaje, no identifican al lead por sí solos |

**No va en este mensaje:** RUT, dirección, ni ningún otro dato demográfico que el motor no
necesite para enviar. Principio de minimización — Ley 21.719.

### 1.2 Evento — `motor → TurboTubo`

El motor reporta, por cada objetivo, si el mensaje llegó o no. Es el único mensaje de escritura.
En Fase 4 este es el payload del webhook (`POST /api/1.0/webhooks/eventos/`), encolado en Celery,
nunca procesado en el proceso web (ver sección 04 del plan de riesgos).

```json
{
  "tipo": "evento",
  "event_id": "c4f1a9e2-...",
  "op": "GAL-0001",
  "target": "principal",
  "canal": "sms",
  "resultado": "entregado",
  "ocurrido_at": "2026-08-15T14:31:12Z"
}
```

Campos:

| Campo | Tipo | Notas |
|---|---|---|
| `event_id` | string (UUID) | clave de idempotencia — TurboTubo descarta duplicados por este id, nunca por contenido |
| `op` | string | debe existir como `Lead.op` en la cartera de la audiencia que lo originó |
| `target` | string | `principal` \| `aval` — igual que en la audiencia |
| `canal` | string | mismo vocabulario que en la audiencia |
| `resultado` | string | uno de los 8 valores de la sección 2 — **nunca** el nombre de un `Resultado` de TurboTubo |
| `ocurrido_at` | string (ISO 8601) | cuándo pasó en el motor, no cuándo llegó el webhook |

**Resultado no reconocido:** si `resultado` no está en el vocabulario de la sección 2, TurboTubo
rechaza el evento completo (HTTP 422) y no crea ningún `Action`. No se adivina ni se cae a un
default — un evento mal formado no puede convertirse silenciosamente en una gestión real.

### 1.3 Resultado — `TurboTubo → motor` (opcional, Fase 6)

Confirmación asíncrona de que el evento fue aplicado (para reconciliación del lado del motor).
No es parte del camino crítico de v1 — se documenta aquí para que el vocabulario quede completo
desde ahora y no haya que romper el contrato después.

```json
{
  "tipo": "resultado",
  "event_id": "c4f1a9e2-...",
  "estado": "aplicado",
  "action_id": 88213
}
```

`estado`: `aplicado` | `rechazado` (con `motivo`) | `duplicado`.

## 2. Vocabulario corto de `resultado`

Ocho valores. Un motor de campañas no necesita más para reportar el estado de un envío masivo.

| `resultado` | Significado |
|---|---|
| `entregado` | El mensaje llegó al destino (SMS/email/WhatsApp/carta confirmados, o IVR completo) |
| `no_entregado` | El mensaje no llegó (rebote, número inexistente, error de envío) |
| `sin_whatsapp` | El destino no tiene WhatsApp activo (específico de ese canal) |
| `humano_detectado` | En IVR/llamada: contestó una persona (no máquina, no buzón) |
| `buzon_detectado` | En IVR/llamada: contestó un contestador/buzón de voz |
| `sin_respuesta` | En IVR/llamada: nadie contestó, tono ocupado, o no se completó |
| `error_conexion` | Falla técnica del canal (no es información sobre el deudor) |
| `no_disponible` | El canal no pudo intentar el contacto (línea caída, proveedor abajo, etc.) |

No hay un noveno valor en v1. Si un motor necesita distinguir algo más fino, eso es señal de que
ya no es una campaña masiva sino una gestión con conversación — y eso lo hace un gestor humano
en TurboTubo, no la API.

## 3. Tabla de mapeo por cartera

La traducción de `resultado` (vocabulario corto) a `Resultado` (árbol real de la cartera) vive
**en TurboTubo**, en una tabla configurable (`actions.MapeoResultadoCampana`, Fase 2) — no en
código del motor. Cartera nueva = filas nuevas en esta tabla, nunca un release del motor.

`medio` es siempre uno fijo por cartera (el que representa "acción masiva" en su árbol). El
`Resultado` a aplicar depende de `canal` + `resultado` recibido.

### 3.1 Galgo — sin código, sin `tipo_contacto`

`medio` fijo: `WHATSAPP` (canal telefónico) o `EMAIL` según `canal` del evento.

| `canal` | `resultado` | → `Resultado.nombre` (Galgo) |
|---|---|---|
| `email` | `entregado` | `MSJ DE CONTACTO` |
| `email` | `no_entregado` | `EMAIL INVALIDO` |
| `whatsapp` | `entregado` | `MSJ DE CONTACTO` |
| `whatsapp` | `no_entregado` | `MSJ DE CONTACTO` *(Galgo no distingue rebote de WhatsApp — ver nota)* |
| `whatsapp` | `sin_whatsapp` | `SIN WHATSAPP` |
| `sms` | `entregado` | `MSJ DE CONTACTO` |
| `sms` | `no_entregado` | `FONO NO CORRESPONDE` |
| cualquiera | `sin_respuesta` | `NO RESPONDE` |
| cualquiera | `humano_detectado` | `MSJ DE CONTACTO` |
| cualquiera | `buzon_detectado` \| `error_conexion` \| `no_disponible` | `NO RESPONDE` |

> Galgo solo tiene 13 resultados y ninguno es específico de WhatsApp-no-entregado — de ahí el
> fallback a `MSJ DE CONTACTO`. Es terreno seguro para validar el contrato (Fase 3) precisamente
> porque no tiene archivo regulatorio de por medio: un mapeo imperfecto aquí no rompe nada que se
> le entregue a un tercero.

### 3.2 Tanner — código + `tipo_contacto = ACCION MASIVA`, medio = `8` (Bot)

Instructivo oficial, columna 15 del archivo regulatorio ya es binaria (`'2'` entregado, `'1'` no
entregado) — el árbol de Tanner ya modela el vocabulario corto de forma casi literal.

| `canal` | `resultado` | → `codigo` Tanner | `Resultado.nombre` |
|---|---|---|---|
| `sms` | `entregado` | `600` | `ENVIO SMS ENTREGADO` |
| `sms` | `no_entregado` | `605` | `ENVIO SMS NO ENTREGADO` |
| `carta` | `entregado` | `601` | `ENVIO CARTA ENTREGADO` |
| `carta` | `no_entregado` | `606` | `ENVIO CARTA NO ENTREGADO` |
| `email` | `entregado` | `602` | `ENVIO EMAIL ENTREGADO` |
| `email` | `no_entregado` | `607` | `ENVIO EMAIL NO ENTREGADO` |
| `whatsapp` | `entregado` | `603` | `ENVIO WHATSAPP ENTREGADO` |
| `whatsapp` | `no_entregado` \| `sin_whatsapp` | `608` | `ENVIO WHATSAPP NO ENTREGADO` |
| `ivr` | `humano_detectado` \| `entregado` | `604` | `ENVIO IVR ENTREGADO` |
| `ivr` | `buzon_detectado` | `609` | `ENVIO IVR INCOMPLETO` |
| `ivr` | `sin_respuesta` \| `no_entregado` \| `error_conexion` \| `no_disponible` | `610` | `ENVIO IVR NO ENTREGADO` |

**Precaución obligatoria (ver sección 07 del plan):** el motor nunca envía `Resultado.nombre`
directamente — solo `resultado` del vocabulario corto. TurboTubo resuelve `codigo` +
`tipo_contacto` contra el catálogo real antes de crear el `Action`. Los códigos `129`–`153`
(`TANNER_CODIGOS_NO_MANUAL`, PAC/venta directa) están fuera del alcance de este mapeo — ningún
valor del vocabulario corto resuelve a esos códigos, y si algo lo intentara, TurboTubo lo
rechaza igual que Omega lo rechazaría (`CODIGOS_BLOQUEADOS`).

### 3.3 Nuevo Capital — sin código numérico, `tipo_contacto = ACCION MASIVA`

| `canal` | `resultado` | → `Resultado.nombre` (Nuevo Capital) |
|---|---|---|
| `sms` | `entregado` | `ENVIO SMS ENTREGADO` |
| `sms` | `no_entregado` | `ENVIO SMS NO ENTREGADO` |
| `email` | `entregado` | `ENVIO EMAIL ENTREGADO` |
| `email` | `no_entregado` | `ENVIO EMAIL NO ENTREGADO` |
| `whatsapp` | `entregado` | `ENVIO WHATSAPP ENTREGADO` |
| `whatsapp` | `no_entregado` \| `sin_whatsapp` | `ENVIO WHATSAPP NO ENTREGADO` |
| `ivr` | `entregado` \| `humano_detectado` | `IVR ENVIADO` |
| `ivr` | `buzon_detectado` | `BUZON DE VOZ` |
| `ivr` | `sin_respuesta` | `NO CONTESTA` |
| `ivr` | `error_conexion` | `ERROR DE CONEXION` |
| `ivr` | `no_disponible` | `FONO NO DISPONIBLE` |

### 3.4 Cartera futura

Una cartera nueva sin fila en la tabla de mapeo hace que TurboTubo rechace el evento con un
error explícito (`cartera sin mapeo configurado`) — nunca cae a un default silencioso ni inventa
un `Resultado`. Agregar una cartera es agregar filas a esta tabla, no tocar el motor.

## 4. Qué NO cubre este contrato (fuera de alcance v1)

- **Autenticación** — API key + HMAC (Fase 2/4), documentado aparte cuando se implemente.
- **Rate limiting / paginación** — específico de cada endpoint, no del vocabulario.
- **`Contacto` maestro y `Segmento`** — descartados por decisión del plan: ese historial ya es
  `Action` en TurboTubo; duplicarlo crea una segunda verdad del deudor.
- **Resultados que requieren conversación** (`PROMESA DE PAGO`, `CESANTE`, montos comprometidos,
  etc.) — un motor de campañas no los produce. Eso solo lo escribe un gestor humano.

## 5. Control de cambios

Este archivo es v1. Cualquier cambio que **agregue** un valor al vocabulario corto o una fila a
una tabla de mapeo es compatible hacia atrás y no requiere subir de versión. Cualquier cambio que
**quite o redefina** un valor existente requiere v2 y coordinación explícita entre ambos repos —
un motor viejo hablando v1 no puede quedar silenciosamente roto.
