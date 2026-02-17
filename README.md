# CW Activator Simulator (POTA)

Aplicacion multiplataforma (Windows/macOS/Linux, Python 3.11+) para practicar un QSO CW corto tipo activador POTA, ahora con interfaz grafica (PySide6).

## Funcionalidades

- Captura de audio en tiempo real desde dispositivo de entrada seleccionable.
- Deteccion de tono CW (Goertzel + auto-tone opcional por FFT).
- Decodificacion Morse a texto con histeresis, AGC basico y estimacion de WPM.
- Maquina de estados QSO POTA (S0..S6) con validaciones y errores claros.
- Respuesta automatica en CW por audio hacia salida seleccionable.
- Modo simulacion por stdin (`--simulate`) para pruebas sin audio.
- Exportacion de logs de sesion en JSON.

## Estructura

- `core/decoder.py`
- `core/encoder.py`
- `core/qso_state_machine.py`
- `ui/app.py` (GUI)
- `config.yaml`
- `tests/`

## Instalacion

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

python -m pip install -r requirements.txt
```

## Ejecucion

GUI:

```bash
python -m app
```

Alternativa:

```bash
python ui/app.py
```

## Seleccion de dispositivos

Listar dispositivos:

```bash
python -m app --list-devices
```

Preseleccionar por CLI:

```bash
python -m app --input-device 3 --output-device 6
```

En la GUI tienes combos de Input/Output para cambiar en caliente.

## Controles en la GUI

- `Reset`
- `Restart QSO` (vuelve a `S0` sin reiniciar decoder)
- `Calibrate`
- `Export Log`
- `Load Calls File` (copia local a `data/other_calls.csv`)
- Toggle `Auto WPM`
- Toggle `Auto Tone`
- Toggle `Require K1`
- Seleccion de Input/Output
- Editor de parametros:
  - `my_call`, `other_call`
  - `cq_mode` (`Simple` / `POTA` / `SOTA`, exclusivo)
  - `prosign` (default `CAVE`) + `Use Prosigns`
  - `wpm_target`, `tone_hz_rx`
  - `message_gap_s` (segundos para considerar fin de envio)
  - `threshold_on`, `threshold_off`
  - `power_smooth`, `gap_char_dots`, `min_up_ratio`
  - `wpm_out`, `tone_hz_out`
  - `allow_599`, `allow_tu`
  - `incoming_call_%` (0/25/50/75/100)
  - Boton `Apply Settings`
- Boton `Log` para expandir/contraer panel de logs.

## Indicadores en pantalla

- Estado actual del QSO (`S0..S6`)
- Nivel de audio (barra + dBFS)
- Tono detectado
- WPM estimado y dot ms
- Estado de key (`UP`/`DOWN`)
- Buffer de texto copiado
- Logs recientes (errores, eventos, respuestas)

## Modo simulacion (sin GUI de audio)

```bash
python -m app --simulate
```

Comandos:

- `/reset`
- `/k1`
- `/export`
- `/quit`

## Parametros relevantes (CLI)

- `--my-call`, `--other-call`
- `--other-calls-file`
- `--wpm-target`, `--wpm-out`
- `--tone-hz`, `--tone-out-hz`
- `--message-gap-sec`
- `--auto-wpm`, `--fixed-wpm`
- `--auto-tone`, `--fixed-tone`
- `--direct-flow`, `--legacy-flow`
- `--require-k1`
- `--allow-599`
- `--allow-tu`
- `--disable-prosigns`
- `--prosign-literal`
- `--s4-prefix R|RR`

## Calibracion recomendada

- Ajusta `tone_hz_rx` cerca del oscilador (ej. 600-700 Hz).
- Si ya conoces el tono (ej. 600 Hz), usa `Auto Tone = OFF`.
- Si hay falsos positivos, sube `threshold_on`.
- Si no detecta puntos cortos, baja `min_key_down_ms` en `config.yaml`.
- Si corta mensajes demasiado pronto/tarde, ajusta `message_gap_s` (GUI) o `message_gap_seconds` (config/CLI).
- Si una `C` (`-.-.`) sale como `M` (`--`), prueba:
  - `Auto Tone = OFF`
  - `power_smooth_alpha = 1.0`
  - `threshold_on = 2.8-3.2`, `threshold_off = 1.6-2.0`
  - `gap_char_threshold_dots = 1.8`
  - `min_key_up_dot_ratio = 0.0`
- Usa `Calibrate` cuando cambie ruido o nivel de entrada.

## Fichero de Indicativos Dinamico

- Formato: texto/CSV por lineas.
- Ignora lineas vacias y lineas que empiezan por `#`.
- En cada linea valida, toma solo el primer campo separado por `,` como indicativo.
- Ejemplo:

```text
# comentario
N1MM,John,MA
K1ABC,Anna
EA4XYZ
```

- Cada nuevo QSO elige un indicativo aleatorio del pool.
- Al cargar desde la GUI se guarda una copia local en `data/other_calls.csv`.
- La app reutiliza ese fichero local al reiniciar y solo cambia cuando cargues uno nuevo.

## Guion QSO soportado

Modo directo (por defecto):

1. CQ segun `qso.cq_mode`:
   - `POTA`: `CQ CQ POTA DE {my_call} {my_call} K` (o `K1` si `require_k1=true`)
   - `SOTA`: `CQ CQ SOTA DE {my_call} {my_call} K` (o `K1`)
   - `SIMPLE`: `CQ CQ {my_call} {my_call} K` (o `K1`)
2. App TX: `{other_call} {other_call}` (`other_call` puede salir de pool dinamico)
3. Usuario: `{other_call} 5NN 5NN` (acepta `599` si `allow_599=true`)
4. App TX: `{prosign_literal} UR 5NN 5NN TU 73 {prosign_literal}` (prosign continuo, sin `my_call`)
5. Usuario: `73 EE`
6. App TX: `EE`, registra QSO y vuelve a S0.
7. Tras cierre, opcionalmente (50% por defecto si esta activado) puede entrar una nueva estacion:
   - App TX: `{other_call} {other_call}`
   - se omite nuevo CQ y se pasa directo al paso de contestar.

Nota: el prosign final se toma de `prosign_literal` y se transmite continuo (sin separacion entre letras).

Modo legado (`direct_report_mode=false` o `--legacy-flow`):

1. CQ segun `qso.cq_mode` (igual que en modo directo)
2. App TX: `{other_call} {other_call}`
3. Usuario: `{other_call}` (1-2 veces)
4. Usuario: `{other_call} UR 5NN 5NN <CAVE>` (si `use_prosigns=true`)
5. App TX: `RR UR 5NN 5NN <CAVE>` (o `R ...`) (si `use_prosigns=true`)
6. Usuario: `<CAVE> 73 EE` (`TU` opcional) si `use_prosigns=true`; o `73 EE` si `use_prosigns=false`
7. App TX: `EE`, registra QSO y vuelve a S0.

Auto-entrada tras QSO:

- `qso.auto_incoming_after_qso`: activa/desactiva llamadas entrantes automaticas tras cerrar QSO.
- `qso.auto_incoming_probability`: probabilidad (0.0-1.0), por ejemplo `0.5` para 50%.

Comportamiento en S2 (tras recibir indicativo de la otra estacion):

- Si envias `?` o parcial con `?` (ej. `K2?`): la app repite el indicativo (`other_call other_call`) y se mantiene en S2.
- Si envias el indicativo completo terminado en `?` (ej. `K2LYV?`): la app responde `RR` y continua flujo.

## Tests

```bash
python -m pytest -q
```

Incluye:

- Roundtrip encoder->decoder sintetico (15/20/25 WPM) con precision >95%.
- Validaciones de maquina de estados: CQ, doble indicativo, `K1`, flujo completo.
