# Layer Audit 

Herramienta de diagnóstico para archivos `.psd` que detecta text layers con coordenadas internas desincronizadas — el problema que causa que la **Adobe Photoshop API** reemplace texto correctamente pero lo posicione fuera del canvas o en coordenadas incorrectas.

Disponible en dos formas:

- **Aplicación de escritorio (`gui.py`)** — para diseñadores. Carga uno o más PSD, muestra una barra de progreso por archivo y lista al final cuáles tienen layers desincronizados. Funciona en Windows, macOS y Linux. Se puede empaquetar como ejecutable único sin necesidad de instalar Python.
- **Línea de comandos (`app.py`)** — script terminal que analiza un PSD a la vez. Útil para automatización o pipelines.

Ambas comparten la misma lógica de detección, definida en `detector.py`.

---

## Aplicación de escritorio (`gui.py`)

### Para diseñadores: usar la versión empaquetada

Una vez que el ejecutable está construido (ver [Empaquetado](#empaquetado-pyinstaller)), distribuirlo es trivial:

| Plataforma | Archivo a copiar | Cómo abrir |
|---|---|---|
| Windows | `DetectorTextoPSD.exe` | doble clic |
| macOS | `DetectorTextoPSD.app` | doble clic (puede requerir permitir en Preferencias → Seguridad la primera vez) |
| Linux | `DetectorTextoPSD` | doble clic o desde terminal `./DetectorTextoPSD` |

No requiere Python ni librerías instaladas en la máquina del diseñador.

### Para desarrolladores: correr desde el código fuente

```bash
pip install -r requirements.txt
python gui.py
```

### Cómo se usa

1. Abrir la aplicación.
2. Click en **Agregar PSDs** y seleccionar uno o varios archivos `.psd`. Soporta lotes grandes (30+ archivos).
3. Click en **Analizar Todo**, o usar el botón **▶** de cada fila para correr individualmente.
   - Procesa en paralelo usando `cpu_count - 1` procesos (mín 2, máx 8).
   - Las filas que no caben en los workers quedan visualmente como `En cola...`.
4. Al terminar, cada fila indica:
   - `OK (N layers)` (verde) — todos los text layers están sincronizados.
   - `N layers fallaran` (rojo) — el PSD tiene problemas.
   - `Error abriendo PSD` (rojo) — archivo corrupto o no soportado.
   - `Sin text layers` (gris) — el PSD no tiene capas de texto.
5. Click en cualquier fila para ver el detalle a la derecha: capa por capa, el delta entre `bounds` y `transform`, y la solución sugerida.
6. Cuando hay problemas detectados aparece el botón **Reparar** — ver siguiente sección.

### Filtro "Ignorar carpetas" (default activo)

El toolbar tiene un checkbox **Ignorar carpetas** activado por defecto. Cuando está marcado, el detector **no analiza layers dentro de Groups regulares** (carpetas de capas).

| Tipo de contenedor | ¿Se recorre? |
|---|---|
| Document root | ✅ siempre |
| Artboard | ✅ siempre (es la "pieza" individual) |
| Group / LayerSection | ❌ se ignora si el checkbox está activo |

**Por qué tiene sentido:** los grupos suelen contener assets compartidos entre todas las plataformas (logos, copy legal fijo, estilos comunes). Esos elementos no se editan via API, así que detectar "problemas" ahí es ruido. Solo nos interesa lo que vive directamente bajo cada artboard.

Si necesitás ver problemas también dentro de grupos, **destildá el checkbox** y vuelve a analizar.

En CLI: `python app.py --include-groups archivo.psd` para incluirlos.

### Mostrar en carpeta

Cada fila tiene un botón **Carpeta** que abre el explorador del SO con el archivo PSD resaltado. El panel de detalles también incluye **Mostrar en carpeta** en la cabecera.

### Reparación automática (botón "Reparar")

Cuando una fila tiene layers desincronizados, aparece el botón **Reparar**. Genera un archivo `<nombre>_fixed.psd` al lado del original (nunca sobreescribe).

**Cómo funciona internamente — cirugía binaria pura.** No reescribe el archivo entero (ningún parser/writer completo de PSD soporta perfectamente todos los modos color y artboards). En cambio, modifica **solo 16 bytes por cada layer desincronizado**, directamente en el binario.

Estructura del chunk `TySh` (TypeToolObjectSetting) en el formato PSD:

```
bytes 0-1   : version (uint16)
bytes 2-49  : transform = 6 doubles big-endian (xx, xy, yx, yy, tx, ty)
              ├─ tx en bytes 34-41
              └─ ty en bytes 42-49
... resto: text descriptor, warp, bounds
```

`binary_repair.py`:

1. Abre el PSD con `psd-tools` para enumerar TypeLayers e identificar cuáles están desincronizados.
2. Para cada uno con `|tx − layer.left| > 500` o `|ty − layer.top| > 500`:
   - Reconstruye el patrón exacto de 48 bytes de su transform original (`struct.pack('>6d', xx, xy, yx, yy, tx, ty)`).
   - Busca ese patrón en el archivo binario (los doubles tienen precisión única → patrón prácticamente único).
   - Sobrescribe solo los 16 bytes de tx/ty con los nuevos valores.
3. Escribe el resultado a `<nombre>_fixed.psd`.

**Qué se preserva (verificado píxel a píxel sobre todos los modos color):**

| Aspecto | Preservación |
|---|---|
| Tamaño del archivo | **idéntico** (+0.000%) |
| Modo color (CMYK / RGB / Grayscale / Lab) | **intacto** |
| Channels | **intactos** |
| Bitmaps de cada capa | **bit a bit idénticos** |
| Smart objects, máscaras, layer comps, ICC | **intactos** |
| Alpha / spot channels, annotations, ajustes | **intactos** |
| Fuentes embebidas, estilos de párrafo | **intactos** |
| Escala y rotación del text layer (xx, xy, yx, yy) | **intactos** |

Lo único que cambia: 16 bytes (tx + ty) por cada layer problemático. Nada más.

**Requisitos:** ninguno extra — Python puro, usa solo `psd-tools` que ya es dependencia del detector. **Funciona offline, sin Node.js, sin Photoshop.**

**Cobertura por modo color:**

| Modo | Soportado |
|---|---|
| RGB | ✅ |
| CMYK | ✅ (impresión profesional) |
| Grayscale | ✅ |
| Lab | ✅ |
| Indexed, Bitmap, Multichannel | ✅ (no se procesan, se copian) |

**UX:**
- Las reparaciones se serializan en un thread (cada PSD se lee/escribe completo en memoria).
- Footer muestra `Reparacion: ON`.

### Prevención (lo más importante)

Lo que el equipo de diseño debe cambiar HOY para que el problema desaparezca de raíz:

| Método | Resultado |
|---|---|
| `Ctrl+C` / `Ctrl+V` entre artboards | ❌ Hereda el desync |
| Drag con Move tool entre artboards | ❌ Hereda el desync |
| `Edit → Paste in Place` (`Ctrl+Shift+V`) | ❌ Igual de problemático |
| **`Layer → Duplicate Layer…` con campo Destination** | ✅ Reconstruye el descriptor |
| Crear el layer de cero en el artboard destino | ✅ Siempre sincronizado |

Photoshop expone el campo *Destination* en el diálogo `Layer → Duplicate Layer…` para elegir el artboard/documento destino. Ese flujo reconstruye el descriptor del layer en el contexto correcto y los `bounds`/`transform` salen consistentes. `Ctrl+C` / `Ctrl+V` clona el descriptor tal cual, perpetuando el desync — no por bug, sino por diseño.

### Empaquetado (PyInstaller)

Para construir el ejecutable distribuible:

```bash
pip install -r requirements-build.txt
python build.py
```

El binario se genera en `dist/DetectorTextoPSD[.exe|.app]`. **Importante:** PyInstaller solo puede construir para la plataforma desde la que se corre. Para tener ejecutables de Windows, macOS y Linux hay que correr `python build.py` una vez en cada sistema operativo.

---

## El problema que resuelve

### Contexto

Cuando se trabaja con la **Adobe Photoshop API** para automatizar el reemplazo de texto en archivos `.psd`, existe un bug silencioso que afecta a ciertos text layers: la API reporta que el reemplazo fue exitoso y el manifest del documento muestra el nuevo contenido, pero visualmente el texto aparece **fuera del artboard**, en coordenadas lejanas, o simplemente invisible.

### Causa raíz

Un text layer de tipo `area` (caja de texto con dimensiones fijas) en un archivo PSD guarda internamente **dos sistemas de coordenadas completamente independientes**:

| Sistema | Propiedad | Qué representa |
|---|---|---|
| Visual | `bounds` (left, top) | Posición que Photoshop muestra en pantalla |
| Interno | `textShape.transform` (tx, ty) | Posición donde el motor de texto renderiza al editar |

En condiciones normales ambos valores están sincronizados. El problema ocurre cuando un text layer es:

- **Copiado con Ctrl+C / Ctrl+V** entre artboards o documentos
- **Arrastrado** de un artboard a otro
- **Movido** con las teclas de flecha después de haber sido pegado desde otro origen

En estos casos Photoshop actualiza los `bounds` (la posición visual) pero **no recalcula el `textShape.transform` interno**. El layer se ve perfectamente en pantalla, pero internamente sus coordenadas reales apuntan a la ubicación original — que puede estar a miles de píxeles de distancia o incluso en coordenadas negativas fuera del canvas.

### Por qué Photoshop no muestran el problema

Tanto Photoshop  usan los `bounds` para renderizar el layer en pantalla. El `textShape.transform` solo se activa cuando el motor de texto necesita **recalcular el layout**, es decir, cuando algo escribe en el layer. Por eso el archivo se ve perfectamente en cualquier editor visual — el bug solo se manifiesta cuando la Photoshop API intenta reemplazar el contenido.

### Qué pasa exactamente durante el fallo

```
1. API recibe instrucción: reemplazar el texto de un layer

2. Motor de texto lee textShape.transform:
   tx y ty apuntan a coordenadas incorrectas o negativas

3. Renderiza el nuevo texto en esas coordenadas absolutas
   (fuera del artboard o del canvas visible)

4. Actualiza bounds con la posición real donde quedó el texto
   → el manifest reporta éxito, pero el texto está fuera de rango
```

### Por qué guardar el PSD lo corrige

Al abrir el archivo, hacer cualquier edición menor y guardar, Photoshop **reconcilia ambos sistemas de coordenadas**: recalcula el `textShape.transform` usando la posición visual actual del layer y los deja sincronizados. La próxima vez que la API escribe en ese layer usa las coordenadas correctas.

---

## Línea de comandos (`app.py`)

### Requisitos
- Python 3.8 o superior
- pip

### Instalar dependencias

```bash
pip install -r requirements.txt
```

### Uso

```bash
python app.py ruta/al/archivo.psd
```

### Ejemplos

```bash
# Windows
python app.py C:\Proyectos\campana.psd
python app.py .\archivo.psd

# Mac / Linux
python app.py /Users/disenio/campana.psd
python app.py ./archivo.psd
```

---

## Interpretación de resultados

### Layer OK
```
[OK] 'Nombre_Del_Layer'  (tx=592, ty=172, Dx=10px, Dy=0px)
```
El layer está sincronizado. `tx` y `ty` son prácticamente iguales a `bounds.left` y `bounds.top`. La pequeña diferencia mostrada es padding interno normal del área de texto. La Photoshop API lo procesará correctamente.

### Layer DESINCRONIZADO
```
[DESINCRONIZADO] 'Nombre_Del_Layer'
    bounds (visual):   left=31, top=1857
    transform interno: tx=-7649.7,  ty=-7231.0
    delta:             Dx=7681px, Dy=9088px
    -> Layer movido/copiado incorrectamente.
       FALLARA al reemplazar texto con la Photoshop API.
```
El layer tiene sus coordenadas internas completamente desincronizadas respecto a su posición visual. Cuando la API reemplace el texto lo posicionará en las coordenadas del `transform` — fuera del canvas o del artboard. **Este layer debe corregirse antes de procesar el PSD.**

La magnitud del delta indica la severidad:
- **Delta > 500px**: layer desincronizado, fallará con certeza
- **Delta de miles de px o negativo**: el layer proviene de un documento completamente diferente

### Reglas de precisión del detector

Un text layer se marca como problema si **cualquiera** de estas dos reglas aplica:

1. **Delta supera el threshold (500 px).**
   `|tx − layer.left| > 500` o `|ty − layer.top| > 500`.
   En la práctica los layers sanos tienen delta < 300 px (padding interno del motor de texto). Layers rotos por copy-paste tienen deltas de miles de px.

2. **Transform fuera del canvas.**
   `tx < −100` o `ty < −100` o `tx > document.width + 100` o `ty > document.height + 100`.
   Esta regla pesca casos donde el delta sería pequeño (ej. 100-400 px) pero la coordenada interna ya cae fuera del canvas. Un layer sano nunca tiene su transform fuera del canvas — eso solo pasa cuando se copió de un lugar inválido.

| Caso real | Delta | Transform fuera del canvas | Regla que lo detecta |
|---|---|---|---|
| Layer sano, padding normal | 0–300 px | No | (no marcado) |
| Copy-paste entre artboards lejanos | 5000+ px | Sí | Ambas |
| Copy-paste entre artboards cercanos | 100–400 px | A veces sí | Out-of-canvas |
| Layer con padding interno alto | 200–450 px | No | (no marcado) |

El panel de detalles muestra el motivo específico junto a cada layer marcado:
- `motivo: delta supera el threshold de 500 px`
- `motivo: transform interno cae fuera del canvas`
- (puede aparecer ambos)

**Falsos positivos**: virtualmente imposibles. La regla de delta tiene margen suficiente para padding normal, y la regla out-of-canvas se aplica solo a coordenadas que un editor sano nunca produciría.

**Falsos negativos**: si dos artboards están a menos de 500 px uno del otro **y** el transform copiado cae dentro del canvas, podríamos no detectarlo. Es un caso raro en stories/posts/banners típicos.

### Layer NO PUDO LEER TRANSFORM
```
[NO PUDO LEER TRANSFORM] 'Nombre_Del_Layer'  (error: ...)
```
El script no pudo acceder a los datos internos del layer. Puede ocurrir con text layers de tipo `point` (texto de una sola línea sin caja de área fija). No se marca como problema automáticamente pero conviene revisarlo manualmente si se sospecha de ese layer.

---

## Cómo corregir un layer desincronizado

Una vez identificado el layer problemático, la corrección es simple:

1. Abrir el PSD en **Photoshop**
2. Realizar cualquier edición menor en el documento:
   - Agregar un layer vacío nuevo y eliminarlo
   - Editar directamente el texto del layer problemático
3. **Guardar** el archivo (Ctrl+S)
4. Volver a correr el script para confirmar que el problema fue resuelto

### Prevención a futuro

La causa del problema siempre es la misma: copiar text layers entre artboards o documentos usando métodos incorrectos.

| Método | Resultado |
|---|---|
| Ctrl+C → Ctrl+V entre artboards | ❌ Desincroniza el transform |
| Drag de un artboard a otro | ❌ Desincroniza el transform |
| `Layer → Duplicate Layer` → seleccionar artboard destino | ✅ Mantiene sincronización |
| Crear el layer desde cero en el artboard destino | ✅ Siempre sincronizado |

---

## Cómo funciona internamente

### Lectura del PSD

```python
from psd_tools import PSDImage
psd = PSDImage.open('archivo.psd')
```

`psd-tools` parsea el formato binario PSD/PSB de Adobe y expone una API Python para acceder a cada layer y sus propiedades internas, incluyendo datos que no son visibles en ninguna interfaz gráfica de Photoshop.

### Acceso al transform

```python
xx, xy, yx, yy, tx, ty = layer.transform
```

`layer.transform` devuelve la **matriz de transformación afín** del `textShape` interno. Para la detección del bug solo importan `tx` y `ty` — las coordenadas absolutas donde el motor de texto ancla el área de escritura.

| Valor | Descripción |
|---|---|
| `xx` | Escala horizontal |
| `xy` | Rotación/skew horizontal |
| `yx` | Rotación/skew vertical |
| `yy` | Escala vertical |
| `tx` | Traslación en X — posición horizontal absoluta en el canvas |
| `ty` | Traslación en Y — posición vertical absoluta en el canvas |

### Comparación y threshold

```python
delta_x = abs(tx - bounds_left)
delta_y = abs(ty - bounds_top)

if delta_x > 500 or delta_y > 500:
    # Layer desincronizado
```

En `psd-tools`, tanto `bounds` como `tx/ty` son coordenadas absolutas respecto al canvas completo. No es necesario sumar offsets de artboard — `psd-tools` ya los normaliza internamente al parsear el archivo.

El threshold de **500px** se determinó empíricamente: las diferencias normales por padding interno y alineación de texto nunca superan los ~300px, mientras que los layers genuinamente desincronizados presentan deltas de 1000px o más. Los 500px son el punto de corte seguro entre ambos grupos.

---

## Limitaciones conocidas

- **Text layers de tipo `point`**: el script puede no leer el transform de layers de texto de una sola línea sin caja de área. Aparecen como `NO PUDO LEER TRANSFORM` y deben verificarse manualmente si generan dudas.
- **Threshold fijo**: el valor de 500px funciona bien en la práctica. Si se encuentran falsos positivos o falsos negativos en documentos muy particulares, se puede ajustar la constante `THRESHOLD_PX` al inicio del script.

---

## Dependencias

| Librería | Versión mínima | Propósito |
|---|---|---|
| `psd-tools` | 1.9.0+ | Parseo de archivos PSD/PSB de Adobe |
| Python | 3.8+ | Lenguaje base |

---

## Contexto técnico adicional

Este bug es específico de la **Adobe Photoshop API**. La API usa el motor de texto nativo de Photoshop para reemplazar contenido, y ese motor lee el `textShape.transform` directamente del archivo PSD para determinar dónde posicionar el texto reemplazado.

Photoshop desktop no manifiestan el bug porque ambos usan `bounds` para el renderizado visual y solo acceden al `textShape.transform` cuando el usuario activamente edita el texto — momento en el cual Photoshop lo recalcula automáticamente antes de usarlo. La API no hace ese recálculo previo, usa el valor almacenado tal cual está en el archivo binario.