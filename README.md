# CW Key trainer 📻

Aplicacion multiplataforma (Windows/macOS/Linux, Python 3.11+) para practicar QSOs CW con audio real (llave + oscilador/micro/line-in/virtual cable) o teclado (VBan o teclas Ctrl), validacion por estados y respuesta automatica en Morse.

## Caracteristicas ✨

- Captura de audio en tiempo real desde dispositivo seleccionable.
- Selector de entrada `Audio` o `Keyboard`.
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
- `data/exchange_patterns.yaml`
- `ui/app.py`
- `config.yaml`
- `tests/`
- `.github/workflows/windows-build.yml`

## Instalacion 🛠️

```bash
git clone https://github.com/dacacioa/cw-keyer-trainer.git
cd cw-keyer-trainer
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

- `Mode` (`Audio` / `Keyboard`)
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

Modo `Keyboard`:

- `Ctrl` izquierda = `dit` (punto), `Ctrl` derecha = `dah` (raya).
- Keyer iambico `A` (doble paleta) con repeticion continua al mantener paleta.
- La velocidad usa `wpm_target`.
- Se inyecta audio interno al decoder (sin `input_device`).
- Se emite sidetone por `output` con `tone_hz_rx` y volumen `encoder.volume`.
- El keying solo actua con la ventana enfocada y runtime en `RUNNING`.
- En este modo no aplican `Input`, `Auto Tone` ni `Calibrate Noise`.
- El sidetone se mezcla con el TX automatico de la app.

Uso rapido de `Keyboard`:

1. Selecciona `Mode = Keyboard`.
2. Ajusta `wpm_target` y `tone_hz_rx`.
3. Pulsa `Apply Settings` y luego `Run`.
4. Manipula con `Ctrl` izquierda/derecha (iambico A).

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
- `p2p_%` (`0/25/50/75/100`, solo en modo `POTA`)
- `my_park_ref` (referencia propia para cierre P2P en S5)
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

## Fichero de parques POTA

- La app usa `qso.parks_file` (por defecto `data/all_parks_ext.csv`).
- Se cargan referencias activas (`active=1`) de la columna `reference`.
- En modo `POTA`, `p2p_%` define la probabilidad de que la primera estacion que llama salga como `P2P`.
- Solo puede haber una estacion `P2P` activa por tanda de llamadas.

## Patrones de intercambio (regex)

Los patrones de validacion de `S0`, `S2`, `S5` y las plantillas TX (`tx`) estan externalizados.
- Fichero activo: `qso.exchange_patterns_file` en `config.yaml` (por defecto `data/exchange_patterns.yaml`).
- El YAML admite raiz `patterns:` o raiz directa (`s0/s2/s5/tx`).
- El contenido se mezcla con defaults internos: puedes sobreescribir solo las claves que necesites.
- Si el fichero no existe o es invalido, la app usa defaults internos y deja un `WARN` en logs.
- Los patrones se cargan al crear `QSOStateMachine` (inicio de app/simulador). Para aplicar cambios, reinicia la app.

El matching se hace sobre texto compactado (sin espacios) y en mayusculas.
Placeholders disponibles:
`{MY_CALL}`, `{OTHER_CALL}`, `{OTHER_CALL_REAL}`, `{PROSIGN}`, `{TX_PROSIGN}`, `{CALL}`, `{PARK_REF}`, `{MY_PARK_REF}`.

Claves soportadas actualmente:
- `s0`: `SIMPLE`, `POTA`, `SOTA`
- `s2`: `report_require_call`, `report_require_call_allow_599`, `report_no_call`, `report_no_call_allow_599`, `p2p_ack`
- `s5`: `with_prosign`, `with_prosign_allow_tu`, `without_prosign`, `without_prosign_allow_tu`, `p2p_with_prosign`, `p2p_with_prosign_allow_tu`, `p2p_without_prosign`, `p2p_without_prosign_allow_tu`
- `tx`: `caller_call`, `repeat_selected_call`, `ack_rr`, `report_reply`, `qso_complete`, `p2p_repeat_call`, `p2p_repeat_ref`, `p2p_station_reply_without_tu`, `p2p_station_reply_with_tu`

Recorte real del fichero por defecto (`data/exchange_patterns.yaml`):

```yaml
patterns:
  s2:
    report_no_call:
      - '^.*(?:[1-5][1-9N][9N]).*(?:[1-5][1-9N][9N]).*$'
    p2p_ack:
      - '^{OTHER_CALL}$'
  tx:
    repeat_selected_call: '{OTHER_CALL} {OTHER_CALL}'
    ack_rr: 'RR'
    p2p_repeat_call: '{OTHER_CALL_REAL} {OTHER_CALL_REAL}'
    p2p_repeat_ref: '{PARK_REF} {PARK_REF}'
    p2p_station_reply_without_tu: 'R R {OTHER_CALL_REAL} {OTHER_CALL_REAL} MY REF {PARK_REF} {PARK_REF} 73 {TX_PROSIGN}'
  s5:
    p2p_without_prosign_allow_tu:
      - '^.*{OTHER_CALL_REAL}.*{MY_CALL}.*MY.*REF.*{MY_PARK_REF}.*{MY_PARK_REF}.*TU.*73.*$'
```

## Guion QSO soportado 📜

### Modo directo (por defecto)

1. CQ segun `qso.cq_mode`:
   - `POTA`: `CQ POTA DE {my_call} K`
   - `SOTA`: `CQ SOTA DE {my_call} K`
   - `SIMPLE`: `CQ DE {my_call} K`
2. App TX: llama entre `1..max_stations` estaciones (aleatorias del pool), cada una con delay aleatorio `0..2s`.
3. Usuario: selecciona una estacion por indicativo exacto y envia reporte (`{other_call} RST RST`, p. ej. `5NN 5NN` o `57N 599`).
4. App TX (QSO normal): `{prosign_literal_tx} UR 5NN 5NN TU 73 {prosign_literal_tx}`.
5. Usuario (QSO normal, S5):
   - sin `allow_tu`: `{prosign_literal_rx} 73 EE` (o `73 EE` si `use_prosigns=false`)
   - con `allow_tu`: `{prosign_literal_rx} TU 73 EE` (o `TU 73 EE` si `use_prosigns=false`)
6. App TX: `EE` y, si quedan estaciones pendientes, vuelven a llamar ignorando `incoming_call_%`.
7. Solo cuando no hay pendientes se aplica `incoming_call_%` para meter una nueva estacion automaticamente.

### Modo P2P (solo en `cq_mode=POTA`)

1. Si `p2p_% > 0`, la primera estacion de la tanda puede salir como `P2P P2P`.
2. Usuario (activador): responde `P2P`.
3. App TX (estacion P2P, por defecto en `data/exchange_patterns.yaml`): `R R {other_call_real} {other_call_real} MY REF {park_ref} {park_ref} [TU] 73 {prosign_literal_tx}`.
   - `park_ref` se envia compactado (sin guion), por ejemplo `US-1234 -> US1234`.
   - `TU` solo se incluye cuando `allow_tu=true`.
4. Usuario (S5 P2P):
   - sin `allow_tu`: `{prosign_literal_rx} {other_call_real} {my_call} MY REF {my_park_ref} {my_park_ref}` (o sin prosign si `use_prosigns=false`)
   - con `allow_tu`: `{prosign_literal_rx} {other_call_real} {my_call} MY REF {my_park_ref} {my_park_ref} TU 73 {prosign_literal_rx}` (o sin prosign si `use_prosigns=false`)
   - ayuda en S5 (solo P2P): `CALL?` repite el indicativo llamante, `REF?` repite la referencia del parque remoto.
5. En el log de completions se guarda: `{real_call} (P2P) {PARK}`.
6. Todo este flujo P2P se valida/forma desde `data/exchange_patterns.yaml` (`s2.p2p_ack`, `tx.p2p_repeat_*`, `tx.p2p_station_reply_*`, `s5.p2p_*`).

Comportamiento en `S2`:

- Indicativo completo con `?` (ej. `EA3IMR?`) => selecciona esa estacion y responde `RR`.
- Parcial con `?` (ej. `EA3?`, `EA?`) => responden solo las estaciones en cola que coinciden.
- Si ya hay estacion seleccionada, cualquier token con `?` repite ese indicativo (`tx.repeat_selected_call`) y se mantiene en `S2`.
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

- `--input-mode audio|keyboard`
- `--my-call`
- `--my-park-ref`
- `--other-call` (fallback cuando no hay pool dinamico)
- `--cq-mode SIMPLE|POTA|SOTA`
- `--other-calls-file`
- `--parks-file`
- `--wpm-target`, `--wpm-out`
- `--wpm-out-start`, `--wpm-out-end`
- `--tone-hz`, `--tone-out-hz`
- `--tone-out-start-hz`, `--tone-out-end-hz`
- `--message-gap-sec`
- `--auto-wpm`, `--fixed-wpm`
- `--auto-tone`, `--fixed-tone`
- `--max-stations`
- `--p2p-percent`
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
