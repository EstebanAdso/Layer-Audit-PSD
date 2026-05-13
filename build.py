"""
build.py
========
Empaqueta gui.py como ejecutable de escritorio con PyInstaller.
Genera un binario unico (--onefile) para la plataforma actual:

    Windows  -> dist/DetectorTextoPSD.exe
    macOS    -> dist/DetectorTextoPSD.app   (bundle)
    Linux    -> dist/DetectorTextoPSD       (binario ELF)

USO:
    pip install -r requirements-build.txt
    python build.py
"""

import platform
import shutil
import subprocess
import sys
from pathlib import Path

APP_NAME = "DetectorTextoPSD"
ENTRY = "gui.py"


def main():
    root = Path(__file__).parent.resolve()
    entry = root / ENTRY
    if not entry.exists():
        print(f"No se encontro {ENTRY}")
        sys.exit(1)

    # Limpieza de builds previos
    for d in ("build", "dist"):
        p = root / d
        if p.exists():
            shutil.rmtree(p)
    for spec in root.glob("*.spec"):
        spec.unlink()

    sysname = platform.system()
    sep = ';' if sysname == "Windows" else ':'
    
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",            # sin consola en Win/Mac
        "--name", APP_NAME,
        "--add-data", f"fixer.jsx{sep}.",
        # psd-tools usa imports dinamicos para sus parsers internos
        "--collect-submodules", "psd_tools",
        str(entry),
    ]

    print(f"Construyendo para {sysname}...")
    print("  " + " ".join(cmd))
    rc = subprocess.call(cmd, cwd=str(root))

    if rc != 0:
        print(f"\nPyInstaller fallo con codigo {rc}")
        sys.exit(rc)

    print("\nBuild OK.")
    dist = root / "dist"
    if sysname == "Windows":
        out = dist / f"{APP_NAME}.exe"
    elif sysname == "Darwin":
        out = dist / f"{APP_NAME}.app"
    else:
        out = dist / APP_NAME

    print(f"Salida: {out}")
    print("\nPuedes copiar este archivo/carpeta y compartirlo")
    print("con el equipo de diseñadores. No requiere Python instalado.")


if __name__ == "__main__":
    main()
