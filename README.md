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

- `Reset`
- `Restart QSO`
- `Calibrate`
- `Export Log`
- `Load Calls File` (guarda copia local en `data/other_calls.csv`)
- `Auto WPM`
- `Auto Tone`
- `Require K1`
- Seleccion `Input`/`Output`

Parametros en settings:

- `my_call`
- `cq_mode` (`Simple` / `POTA` / `SOTA`, exclusivo)
- `prosign` + `Use Prosigns`
- `wpm_target` (RX) y `wpm_out` (TX de la otra estacion)
- `tone_hz_rx` y `tone_hz_out`
- `threshold_on`, `threshold_off`
- `power_smooth`, `gap_char_dots`, `min_up_ratio`
- `message_gap_s`
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
   - `POTA`: `CQ CQ POTA DE {my_call} {my_call} K` (o `K1` con `require_k1=true`)
   - `SOTA`: `CQ CQ SOTA DE {my_call} {my_call} K` (o `K1`)
   - `SIMPLE`: `CQ CQ {my_call} {my_call} K` (o `K1`)
2. App TX: `{other_call} {other_call}`
3. Usuario: `{other_call} 5NN 5NN` (acepta `599` si `allow_599=true`)
4. App TX: `{prosign_literal} UR 5NN 5NN TU 73 {prosign_literal}` (sin `my_call`)
5. Usuario: `73 EE`
6. App TX: `EE`, se registra QSO y vuelve a `S0`.
7. Si esta activo auto-incoming, puede entrar nueva estacion segun `incoming_call_%` y se salta CQ.

### Modo legado (`--legacy-flow`)

1. CQ segun `qso.cq_mode`
2. App TX: `{other_call} {other_call}`
3. Usuario: `{other_call}` (1-2 veces)
4. Usuario: `{other_call} UR 5NN 5NN <CAVE>` (si `use_prosigns=true`)
5. App TX: `RR UR 5NN 5NN <CAVE>` (o `R ...`)
6. Usuario: `<CAVE> 73 EE` (o `73 EE` si `use_prosigns=false`)
7. App TX: `EE`, se registra QSO y vuelve a `S0`.

Comportamiento en `S2`:

- `?` o parcial con `?` (ej. `K2?`) => repite indicativo (`other_call other_call`) y sigue en `S2`.
- Indicativo completo terminado en `?` (ej. `K2LYV?`) => responde `RR` y continua flujo.

## Modo simulacion (sin audio) 🧪

```bash
python -m app --simulate
```

Comandos:

- `/reset`
- `/k1`
- `/export`
- `/quit`

## CLI relevante ⌨️

- `--my-call`
- `--other-call` (fallback cuando no hay pool dinamico)
- `--cq-mode SIMPLE|POTA|SOTA`
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
- Construye `CWKeyTrainer.exe` con PyInstaller.
- Genera ZIP: `CWKeyTrainer-windows-<tag>.zip`.
- Sube el ZIP como:
  - artifact del workflow
  - asset de la Release
- Descarga siempre la ultima version desde la `latest release`:
  - URL: `https://github.com/<owner>/<repo>/releases/latest`
  - Ahí encontraras el asset `CWKeyTrainer-windows-<tag>.zip`.

## Tests ✅

```bash
python -m pytest -q
```

Incluye:

- Roundtrip encoder->decoder sintetico (15/20/25 WPM) con precision >95%.
- Validaciones de maquina de estados (CQ, doble indicativo, `K1`, flujo directo/legado, casos con `?`).
