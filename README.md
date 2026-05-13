# Layer Audit PSD

**Layer Audit PSD** es una herramienta profesional diseñada para detectar y corregir problemas estructurales en archivos Photoshop (.psd / .psb), optimizando archivos para flujos de trabajo de automatización.

---

## 🪟 Guía para Windows (Paso a Paso)

### 1. Instalación de Python
*   Descarga e instala **Python 3.10 o superior** desde [python.org](https://www.python.org/downloads/windows/).
*   **IMPORTANTE:** Durante la instalación, marca la casilla que dice **"Add Python to PATH"**.

### 2. Configuración del Proyecto
*   Descarga el código y abre una terminal (CMD o PowerShell) en la carpeta del proyecto.
*   (Opcional) Crea un entorno virtual:
    ```powershell
    python -m venv venv
    .\venv\Scripts\activate
    ```
*   Instala las librerías necesarias:
    ```powershell
    pip install -r requirements.txt
    ```

### 3. Ejecución
*   Para iniciar la aplicación visual:
    ```powershell
    python gui.py
    ```

### 4. Empaquetado (Crear el .exe)
*   Si quieres generar un ejecutable para compartir con otros:
    ```powershell
    pip install -r requirements-build.txt
    python build.py
    ```
*   El archivo aparecerá en la carpeta `dist/Layer Audit PSD.exe`.

---

## 🍎 Guía para macOS (Paso a Paso)

### 1. Instalación de Python y Dependencias de Sistema
*   Instala **Python 3.10+** desde [python.org](https://www.python.org/downloads/macos/) o vía Homebrew.
*   **IMPORTANTE:** macOS requiere instalar `tkinter` manualmente si usas Homebrew:
    ```bash
    brew install python-tk
    ```

### 2. Configuración del Proyecto
*   Abre la Terminal en la carpeta del proyecto.
*   (Opcional) Crea un entorno virtual:
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```
*   Instala las librerías necesarias:
    ```bash
    pip install -r requirements.txt
    ```

### 3. Ejecución
*   Para iniciar la aplicación visual:
    ```bash
    python3 gui.py
    ```

### 4. Empaquetado (Crear el .app)
*   Si quieres generar una aplicación nativa de Mac:
    ```bash
    pip install -r requirements-build.txt
    python3 build.py
    ```
*   La aplicación aparecerá en la carpeta `dist/Layer Audit PSD.app`.

---

## 🚀 ¿Cómo usar la aplicación?

1.  **Agregar Archivos:** Usa el botón `+ Agregar PSDs` para cargar tus archivos.
2.  **Analizar:** Haz clic en `Analizar Todo` o en el icono `▶` de cada fila.
    *   **Verde (OK):** El archivo está perfecto.
    *   **Rojo (Problemas):** Se detectaron capas desincronizadas o Smart Objects duplicados.
3.  **Corregir:** Selecciona un archivo con problemas y pulsa `Corregir en Photoshop`. 
    *   Esto abrirá Photoshop automáticamente.
    *   Se creará una copia del archivo con el sufijo `_fixed.psd`.
4.  **Ver Resultado:** Una vez que el estado cambie a "REPARADO", pulsa `Ver archivo reparado` para abrir la carpeta con el nuevo archivo seleccionado.

---

## 🔍 Problemas técnicos que resuelve

### 1. Text Layers Desincronizados
Evita que los textos "salten" de posición al ser reemplazados vía API. Sincroniza los *bounds* visuales con la matriz de transformación interna de Photoshop.

### 2. Smart Objects Compartidos
Identifica capas que comparten el mismo asset interno (UUID), evitando que al editar una imagen se cambien accidentalmente todas las demás instancias que deberían ser independientes.

---

**Desarrollado para equipos de diseño y automatización.**
