# Layer Audit PSD

Herramienta de auditoría y reparación de archivos Photoshop (`.psd` / `.psb`) que sufren **herencia de transform corrupto** cuando el equipo de diseño copia/pega capas de texto entre artboards. Su objetivo es que esos PSDs sean utilizables por automatizaciones que reemplazan texto e imágenes vía la Photoshop API (o equivalentes), sin que el contenido sustituido termine en la posición equivocada o fuera del canvas.

---

## El problema que resuelve

Cuando un diseñador hace **Ctrl+C / Ctrl+V** de una capa de texto entre dos artboards en el mismo PSD, Photoshop actualiza los `bounds` visuales de la copia pero **deja el transform interno (`tx`, `ty`) apuntando al artboard original**. Visualmente la capa se ve donde corresponde, pero al reemplazar su texto programáticamente (`textItem.contents = "..."`), Photoshop reposiciona el contenido usando los anchors internos corruptos y el texto aparece a miles de píxeles del lugar correcto.

Lo mismo pasa con **Smart Objects**: un Ctrl+V duplica el layer pero ambos apuntan al mismo asset embebido (mismo `unique_id`), así que editar uno modifica todos.

Ambos problemas son invisibles para el diseñador, salen a la luz solo cuando la pipeline de automatización corre y empieza a producir piezas rotas. Este proyecto los detecta y repara antes de que lleguen a producción.

---

## Stack tecnológico

| Capa | Tecnología | Por qué |
|---|---|---|
| **Detección** | Python 3.10+ con [`psd-tools`](https://github.com/psd-tools/psd-tools) | `psd-tools` parsea PSD/PSB sin tener Photoshop instalado. Lee el descriptor `TyShO`, el `EngineData` (motor de texto de Adobe) y los `image_resources`. Permite analizar lotes grandes en paralelo. |
| **Reparación** | Node.js 18+ con [`ag-psd`](https://www.npmjs.com/package/ag-psd) | `ag-psd` lee y **escribe** PSD respetando los descriptores. No necesita Photoshop. Reemplazó al fixer original basado en `fixer.jsx` (que sí requería Photoshop instalado + COM/AppleScript). |
| **Interfaz** | Tkinter (stdlib de Python) | Multiplataforma, sin dependencias extra. Soporta `ProcessPoolExecutor` para analizar varios PSDs en paralelo sin chocar con el GIL. |
| **Empaquetado** | PyInstaller | Genera `.exe` (Windows) y `.app` (macOS) para los diseñadores. *Nota:* el .exe actual no empaqueta el motor Node de reparación; ver sección "Limitaciones". |

### Por qué cada librería

- **`psd-tools`** es la única librería madura en Python que entiende el formato `TyShO` de capas de texto, incluyendo el `EngineData` (un blob binario con el modelo de texto del motor de Adobe — fuentes, estilos, `ShapeType`, `boxBounds`). Lectura pura, no escribe.
- **`ag-psd`** es la única librería JS que respeta la estructura interna de los descriptores al escribir. Su round-trip preserva la mayoría de los campos. Tiene patches custom en `agpsd/patch_ag_psd.js` para suplir lo que no preserva por defecto (ver Hallazgos).
- **`canvas`** (peer dep de ag-psd) — necesaria solo porque ag-psd usa Canvas para decodificar imágenes incluso si pasas `useImageData: false`.

---

## Hallazgos clave (lo que aprendimos en el camino)

Estos son los puntos no obvios. Todos están codificados en los algoritmos pero conviene tenerlos explícitos.

### 1. Photoshop posiciona point text y paragraph text con fórmulas distintas

Al reemplazar el contenido de una capa de texto con la Photoshop API, Photoshop **no usa `tx, ty` directamente**. Usa una de dos fórmulas según el tipo:

| Tipo (`ShapeType`) | Fórmula efectiva | Anchor crítico |
|---|---|---|
| **Point** (`ShapeType=0`) | `visual.x = tx + xx · boundingBox.left` | `boundingBox` + escala |
| **Paragraph** (`ShapeType=1`) | `visual.x = tx + 2 · boxBounds[0]` | `boxBounds` (en EngineData) |

Consecuencia práctica:

- **Solo paragraph text rompe la API** cuando se copia/pega. El `boxBounds` queda con coordenadas del artboard origen y como típicamente `xx = 1` (sin escala), no hay nada que absorba el error → el texto se planta fuera del canvas.
- **Point text NO rompe la API**, aunque el detector vea un `delta` enorme entre `tx` y `bounds.left`. Eso pasa cuando el diseñador hizo Free Transform escalando la capa (ej. `xx = 3.77×`): Photoshop almacenó un `tx` muy negativo y un `boundingBox.left` muy grande, y al multiplicar por la escala da exactamente la posición visual correcta.

Por eso la GUI tiene un checkbox **"Ignorar capas point"** activado por defecto: filtra falsos positivos de capas point con delta grande pero que renderizan bien. Si lo destildas, ves todos los casos (útil para auditar hábitos del equipo aunque no impacten la pipeline).

### 2. La reparación para paragraph text requiere resetear `boxBounds`

`boxBounds` es un campo **no documentado** que vive dentro del `EngineData`. ag-psd lo expone como `text.boxBounds = [L, T, R, B]`. La reparación de `agpsd/test11_boxbounds.js`:

```
bounds      → (0, 0, W, H)            // reseteo a coordenadas locales
boundingBox → relativo a (0, 0) con offset original preservado
boxBounds   → [0, 0, Wbox, Hbox]      // ¡crítico! sin esto el texto sigue saltando
transform   → (xx, xy, yx, yy, target.left, target.top)
```

Resetear `bounds` y `boundingBox` por sí solo NO arregla el problema. **El campo que decide la posición final es `boxBounds`** — si no lo reseteas, Photoshop sigue usando los `boxBounds` corruptos al re-renderizar y el texto vuelve a saltar.

### 3. ag-psd descarta image resources críticos al escribir

ag-psd tiene handlers internos para `ICC_PROFILE` (1039), `EXIF_DATA_1` (1058), `COLOR_HALFTONING_INFO` (1013), `COLOR_TRANSFER_FUNCTION` (1016) y `IPTC_NAA` (1028), pero **están gated bajo `MOCK_HANDLERS = false`** y nunca se registran. Resultado: el round-trip elimina el perfil ICC embebido.

Sin perfil ICC, Photoshop al abrir el PSD reparado asume "documento sin perfil" y aplica el working space del usuario. **Los colores se ven distintos** (típicamente más opacos o desaturados). El primer fixed que generamos se veía visiblemente mal hasta que descubrimos esto.

**Fix en `agpsd/patch_ag_psd.js`**: registramos manualmente handlers byte-passthrough para esos resources. El round-trip ahora preserva los colores exactos del original.

### 4. El detector necesita reglas distintas para texto vertical

Photoshop almacena la línea base del texto vertical en `ty`, así que `ty` puede legítimamente caer fuera del canvas en capas sanas. La regla de "transform fuera del canvas" se evalúa solo en el eje X cuando la capa tiene `Ornt = b'Vrtc'` en su TyShO.

Texto horizontal rotado 90° **no** es texto vertical real — `Ornt` sigue siendo `b'Hrzn'` y el bbox queda alto y delgado. El detector infiere rotación cuando `height / width > 5` con `Ornt='Hrzn'`.

### 5. La fuente real vive en `engine_dict.FontSet`, no en el descriptor en vivo

Photoshop sustituye fuentes en tiempo de ejecución cuando el transform de una capa está corrupto. `textItem.font` o `fontPostScriptName` del descriptor en vivo devuelve la fuente sustituta (típicamente Myriad Pro), **no la original** del PSD. La fuente verdadera hay que leerla de los bytes crudos: `engine_dict.StyleRun.RunArray[0].StyleSheet.StyleSheetData.Font` indexado contra `layer.resource_dict.FontSet`.

### 6. El inner `transform.tx/ty` NO está en coordenadas de canvas

(Este hallazgo es del antiguo flujo basado en `fixer.jsx`, conservado por contexto.) Al setear `tx/ty` a un target en pixeles del canvas vía ScriptingListener / ActionDescriptor, Photoshop rechaza con "result too large". El truco era setear `tx/ty = 0` (identity), dejar que `setd` rerendere y luego ajustar la posición vía `move` en pasos pequeños.

ag-psd opera al nivel del descriptor binario directamente y no tiene esta limitación.

---

## Arquitectura

```
+---------------------------+         +-----------------------------+
|  GUI (Tkinter, gui.py)    |         |  CLI (app.py)               |
|  ProcessPoolExecutor      |         |                             |
+------------+--------------+         +--------------+--------------+
             |                                       |
             v                                       v
        +----+---------------------------------------+----+
        |  detector.py  (psd-tools, sin Photoshop)       |
        |  analyze_psd() -> problems[], smart_objects[]  |
        +----+-------------------------------------------+
             |
             v   (al hacer click en "Corregir capas")
        +----+----------------------------------------+
        |  fixer.py  (subprocess hacia Node)          |
        |  - arma manifest JSON                       |
        |  - corre: node agpsd/test11_boxbounds.js    |
        +----+----------------------------------------+
             |
             v
        +----+----------------------------------------+
        |  agpsd/test11_boxbounds.js  (Node + ag-psd) |
        |  - reset bounds/boundingBox/boxBounds       |
        |  - transform -> (xx, xy, yx, yy, target)    |
        |  - escribe <basename>_fixed.psd             |
        +---------------------------------------------+
```

El archivo de entrada nunca se modifica: la reparación produce siempre `<basename>_fixed.psd` al lado del original.

---

## Instalación

### Windows

```powershell
# 1. Python 3.10+ con "Add Python to PATH"
# 2. Node.js 18+ (https://nodejs.org)
pip install -r requirements.txt
cd agpsd && npm install
```

### macOS

```bash
brew install python-tk node
pip3 install -r requirements.txt
cd agpsd && npm install
```

### Uso

```powershell
python gui.py                          # GUI completa (análisis + reparación)
python app.py archivo.psd              # CLI: solo detección, sin reparar
python app.py --include-groups arch.psd  # incluir también capas dentro de carpetas
```

### Build standalone

```powershell
pip install -r requirements-build.txt
python build.py
# salida: dist/DetectorTextoPSD.{exe,app}
```

---

## Uso de la GUI

1. **Agregar archivos** con `+ Agregar PSDs` (botón superior).
2. **Analizar** con `Analizar Todo` o el icono `▶` por fila.
   - 🟢 **OK**: archivo limpio.
   - 🔴 **Problemas**: hay capas de texto con transform corrupto o Smart Objects compartidos.
3. **Toggles de filtrado**:
   - `Ignorar carpetas` — no analiza capas dentro de Groups normales (sí dentro de Artboards). Útil porque los Groups suelen contener assets fijos (logos, legales) que no se modifican via automatización.
   - `Ignorar capas point` — no marca como problema las capas point text aunque tengan delta grande. Es el default porque la Photoshop API las renderiza bien (ver Hallazgo #1). Destíldalo si quieres auditar hábitos del equipo aunque no impacten producción.
4. **Corregir** un PSD con problemas → genera `<nombre>_fixed.psd` al lado del original. El original nunca se toca.
5. **Ver archivo reparado** → abre el explorador con el nuevo archivo seleccionado.

---

## Limitaciones conocidas

- **El `.exe` empaquetado por `build.py` no incluye Node.js ni `agpsd/`.** La detección funcionará pero el botón "Corregir capas" mostrará "Node.js no detectado" salvo que el usuario tenga Node instalado y `agpsd/` esté junto al ejecutable. Si se requiere distribución autocontenida, hay que decidir entre (a) bundlear un Node portable + `agpsd/`, o (b) reescribir la reparación en Python (pendiente — `ag-psd` no tiene equivalente Python con escritura igual de fiel).
- **`test11_boxbounds.js` está validado para texto horizontal point y paragraph.** Texto vertical y rotado pasa por el mismo algoritmo pero su corrección no está exhaustivamente validada — tratarlo como territorio de iteración.
- **Smart Objects compartidos se detectan pero no se reparan automáticamente.** La GUI los lista; la corrección requiere intervención manual en Photoshop (Layer → Smart Objects → New Smart Object via Copy en cada instancia).
- **`fixer.jsx`** (~1500 líneas) sigue en el repo por referencia histórica del flujo viejo basado en Photoshop. No se invoca desde la GUI actual.

---

## Documentación de desarrollo

Para detalles internos (algoritmos exactos de `check_type_layer`, contrato Python ↔ Node, gotchas al editar), ver [`CLAUDE.md`](./CLAUDE.md).
