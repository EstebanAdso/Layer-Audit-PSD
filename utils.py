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
