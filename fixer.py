import json
import os
import platform
import subprocess
import tempfile

def run_photoshop_script(jsx_path, psd_path):
    """Ejecuta un script JSX en Photoshop de forma multiplataforma y no bloqueante."""
    sys_name = platform.system()
    try:
        if sys_name == 'Windows':
            safe_jsx_path = jsx_path.replace("\\", "\\\\")
            safe_psd_path = psd_path.replace("\\", "\\\\")
            
            # VBScript que abre el PSD, espera un poco y luego lanza el script
            vbs_content = (
                'On Error Resume Next\n'
                'Set app = CreateObject("Photoshop.Application")\n'
                f'app.Open("{safe_psd_path}")\n'
                'WScript.Sleep 2000\n' # Esperar 2 seg para asegurar que abre
                f'app.DoJavaScriptFile("{safe_jsx_path}")\n'
                'Set app = Nothing'
            )
            vbs_path = os.path.join(tempfile.gettempdir(), "launch_ps.vbs")
            
            with open(vbs_path, 'w', encoding='utf-16') as f:
                f.write(vbs_content)
            
            subprocess.Popen(['cscript', '//Nologo', vbs_path], 
                            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0)
            return True
        elif sys_name == 'Darwin': # macOS
            # En Mac usamos open -a que es inteligente
            subprocess.Popen(['open', '-a', 'Adobe Photoshop', psd_path])
            # Esperar un poco antes de lanzar el script
            import time
            time.sleep(2)
            subprocess.Popen(['open', '-a', 'Adobe Photoshop', jsx_path])
            return True
        return False
    except Exception as e:
        print(f"Error crítico al lanzar script: {e}")
        return False

def fix_layers_in_psd(psd_path, layer_data):
    """Prepara datos y lanza el proceso de corrección."""
    if not layer_data:
        return False

    temp_dir = tempfile.gettempdir()
    json_path = os.path.join(temp_dir, "psd_layers_to_fix.json")
    done_path = os.path.join(temp_dir, "psd_fix_done.txt")
    log_path = os.path.join(temp_dir, "psd_fix_log.txt")
    
    try:
        for stale_path in (done_path, log_path):
            if os.path.exists(stale_path):
                os.remove(stale_path)
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(layer_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error al escribir JSON: {e}")
        return False

    import sys
    if hasattr(sys, '_MEIPASS'):
        base_dir = sys._MEIPASS
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        
    jsx_path = os.path.join(base_dir, "fixer.jsx")
    
    if not os.path.exists(jsx_path):
        print(f"No existe fixer.jsx en {jsx_path}")
        return False

    return run_photoshop_script(jsx_path, psd_path)
