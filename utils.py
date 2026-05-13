"""
utils.py
========
Utilidades compartidas por la GUI.
"""

import os
import platform
import subprocess


def reveal_in_file_manager(path):
    """Abre el archivo en el explorador del SO y, si es posible, lo selecciona."""
    if not path or not os.path.exists(path):
        return False
    sysname = platform.system()
    try:
        if sysname == 'Windows':
            # /select, resalta el archivo en Explorer
            subprocess.Popen(['explorer', '/select,', os.path.abspath(path)])
        elif sysname == 'Darwin':
            subprocess.Popen(['open', '-R', os.path.abspath(path)])
        else:
            subprocess.Popen(['xdg-open', os.path.dirname(os.path.abspath(path))])
        return True
    except Exception:
        return False


def check_photoshop_installed():
    """Verifica si Adobe Photoshop está instalado en el sistema."""
    sysname = platform.system()
    try:
        if sysname == 'Windows':
            # Intentar buscar en el registro de clases COM
            import winreg
            try:
                # Photoshop.Application es el ID de objeto COM estándar
                with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "Photoshop.Application") as key:
                    return True
            except FileNotFoundError:
                # Segundo intento: buscar en App Paths
                try:
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, 
                                        r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\Photoshop.exe") as key:
                        return True
                except FileNotFoundError:
                    return False
        
        elif sysname == 'Darwin':
            # En Mac usamos 'mdfind' para buscar por Bundle ID o el comando open con -Ra
            # 'open -Ra "Adobe Photoshop"' devuelve 0 si existe
            res = subprocess.run(['open', '-Ra', 'Adobe Photoshop'], 
                                 capture_output=True, text=True)
            return res.returncode == 0
        
        return True # En otros sistemas no controlamos pero dejamos pasar
    except Exception:
        return False
