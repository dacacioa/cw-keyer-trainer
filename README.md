# CW Key trainer 🔑📻

Aplicacion multiplataforma (Windows/macOS/Linux, Python 3.11+) para practicar QSOs CW con audio real (llave + oscilador/micro/line-in/virtual cable), validacion por estados y respuesta automatica en Morse.

## Caracteristicas ✨

- Captura de audio en tiempo real desde dispositivo seleccionable.
- Deteccion de tono CW (Goertzel + auto-tone opcional).
- Decodificacion Morse a texto con histeresis, AGC basico y estimacion de WPM.
- Maquina de estados de QSO con validaciones y mensajes de error claros.
- TX automatica en CW hacia dispositivo de salida seleccionable.
- Modo simulacion por stdin (`--simulate`) para pruebas sin audio.
- Exportacion de sesion/logs en JSON.

## Estructura del proyecto 🧱

- `core/decoder.py`
- `core/encoder.py`
- `core/qso_state_machine.py`
- `ui/app.py`
- `config.yaml`
- `tests/`
- `.github/workflows/windows-build.yml`

## Instalacion 🛠️

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

python -m pip install -r requirements.txt
```

## Ejecucion ▶️

GUI:

```bash
python -m app
```

Alternativa:

```bash
python ui/app.py
```

## Dispositivos de audio 🎚️

Listar dispositivos:

```bash
python -m app --list-devices
```

Preseleccionar por CLI:

```bash
python -m app --input-device 3 --output-device 6
```

## GUI actual (compacta) 🖥️

La parte superior esta compactada en dos columnas:

- Columna izquierda: `QSO Status` + `Signal`.
- Columna derecha: `Runtime Controls` + `QSO/Decoder/Encoder Settings`.

Notas de UI recientes:

- `QSO Status` muestra solo `State`.
- Boton `Clear Decoding` para limpiar el buffer de texto decodificado.
- Boton `Log` para expandir/contraer el panel de logs.
- El campo `other_call` ya no se edita en GUI.

Controles runtime:

- `Run`
- `Pause`
- `Stop`
- `Restart QSO`
- `Calibrate`
- `Export Log`
- `Load Calls File` (guarda copia local en `data/other_calls.csv`)
- `Auto WPM`
- `Auto Tone`
- Seleccion `Input`/`Output`

Parametros en settings:

- `my_call`
- `cq_mode` (`Simple` / `POTA` / `SOTA`, exclusivo)
- `prosign` + `Use Prosigns`
- `wpm_target` (RX), `wpm_out_start` y `wpm_out_end` (TX aleatorio por QSO)
- `tone_hz_rx`, `tone_hz_out_start` y `tone_hz_out_end` (TX aleatorio por QSO)
- `threshold_on`, `threshold_off`
- `power_smooth`, `gap_char_dots`, `min_up_ratio`
- `message_gap_s`
- `max_stations` (cantidad maxima de estaciones en cola tras cada CQ)
- `incoming_call_%` (`0/25/50/75/100`)
- `allow_599`, `allow_tu`

## Indicadores en pantalla 📈

- Estado del QSO (`S0..S6`)
- Nivel de audio (barra + dBFS)
- Tono detectado
- WPM estimado + dot ms
- Estado de key (`UP`/`DOWN`)
- Buffer de texto copiado
- Logs de eventos/errores

## Fichero dinamico de indicativos 📂

Formato:

- Texto/CSV por lineas.
- Se ignoran lineas vacias y lineas que empiezan por `#`.
- De cada linea valida se usa solo el primer campo separado por `,` como indicativo.

Ejemplo:

```text
# comentario
N1MM,John,MA
K1ABC,Anna
EA4XYZ
```

Comportamiento:

- Cada nuevo QSO elige un indicativo aleatorio del pool.
- Al cargar en GUI se copia a `data/other_calls.csv`.
- Ese fichero local se reutiliza en siguientes arranques.
- Si no hay pool cargado, se usa `qso.other_call` como fallback interno.

## Guion QSO soportado 📜

### Modo directo (por defecto)

1. CQ segun `qso.cq_mode`:
   - `POTA`: `CQ CQ POTA DE {my_call} {my_call} K`
   - `SOTA`: `CQ CQ SOTA DE {my_call} {my_call} K`
   - `SIMPLE`: `CQ CQ {my_call} {my_call} K`
2. App TX: llama entre `1..max_stations` estaciones (aleatorias del pool), cada una con delay aleatorio `0..2s`.
3. Usuario: selecciona una estacion por indicativo exacto y envia reporte (`{other_call} 5NN 5NN`).
4. App TX: `{prosign_literal} UR 5NN 5NN TU 73 {prosign_literal}` (sin `my_call`)
5. Usuario: `73 EE`
6. App TX: `EE` y, si quedan estaciones pendientes, vuelven a llamar ignorando `incoming_call_%`.
7. Solo cuando no hay pendientes se aplica `incoming_call_%` para meter una nueva estacion automaticamente.

Comportamiento en `S2`:

- Indicativo completo con `?` (ej. `EA3IMR?`) => selecciona esa estacion y responde `RR`.
- Parcial con `?` (ej. `EA3?`, `EA?`) => responden solo las estaciones en cola que coinciden.
- Si no hay coincidencias para el patron, no responde ninguna estacion.

## Modo simulacion (sin audio) 🧪

```bash
python -m app --simulate
```

Comandos:

- `/reset`
- `/export`
- `/quit`

## CLI relevante ⌨️

- `--my-call`
- `--other-call` (fallback cuando no hay pool dinamico)
- `--cq-mode SIMPLE|POTA|SOTA`
- `--other-calls-file`
- `--wpm-target`, `--wpm-out`
- `--wpm-out-start`, `--wpm-out-end`
- `--tone-hz`, `--tone-out-hz`
- `--tone-out-start-hz`, `--tone-out-end-hz`
- `--message-gap-sec`
- `--auto-wpm`, `--fixed-wpm`
- `--auto-tone`, `--fixed-tone`
- `--max-stations`
- `--allow-599`
- `--allow-tu`
- `--disable-prosigns`
- `--prosign-literal`
- `--s4-prefix R|RR`

## Calibracion recomendada 🎯

- Ajusta `tone_hz_rx` cerca del oscilador (ej. `600-700 Hz`).
- Si conoces tono fijo, usa `Auto Tone = OFF`.
- Si hay falsos positivos, sube `threshold_on`.
- Si corta mensajes antes/despues de tiempo, ajusta `message_gap_s`.
- Si una `C` (`-.-.`) sale como `M` (`--`), prueba:
  - `Auto Tone = OFF`
  - `power_smooth_alpha = 1.0`
  - `threshold_on = 2.8-3.2`, `threshold_off = 1.6-2.0`
  - `gap_char_threshold_dots = 1.8`
  - `min_key_up_dot_ratio = 0.0`
- Usa `Calibrate` cuando cambie ruido o nivel.

## Build Windows en GitHub Release 🪟🚀

Workflow: `.github/workflows/windows-build.yml`

Comportamiento:

- Se ejecuta al publicar una Release (`release: published`).
- Ejecuta tests.
- Construye paquete `onedir` con PyInstaller (arranque mas rapido que `onefile`).
- Genera ZIP: `CWKeyTrainer-windows-<tag>.zip`.
- Sube el ZIP como:
  - artifact del workflow
  - asset de la Release
- Dentro del ZIP, ejecuta `CWKeyTrainer\CWKeyTrainer.exe`.
- Descarga siempre la ultima version desde la `latest release`:
  - URL: `https://github.com/<owner>/<repo>/releases/latest`
  - Ahí encontraras el asset `CWKeyTrainer-windows-<tag>.zip`.

## Tests ✅

```bash
python -m pytest -q
```

Incluye:

- Roundtrip encoder->decoder sintetico (15/20/25 WPM) con precision >95%.
- Validaciones de maquina de estados (CQ, cola de estaciones, seleccion por indicativo y casos con `?`).
