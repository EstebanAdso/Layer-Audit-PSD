
import os
import time
import tempfile
import json
from detector import analyze_psd
from fixer import fix_layers_in_psd

def test_full_cycle():
    psd_path = os.path.abspath("01_Story.psd")
    print(f"--- 1. Analizando {psd_path} ---")
    res = analyze_psd(psd_path)
    
    if not res['problems']:
        print("No se encontraron problemas iniciales (¿ya está corregido?).")
        # Forzar data de una capa para probar el lanzamiento
        layer_data = [{
            'name': res['layers'][0]['name'],
            'layer_id': res['layers'][0].get('layer_id'),
            'template_layer_id': res['layers'][0].get('template_layer_id'),
            'template_layer_name': res['layers'][0].get('template_layer_name'),
            'width': res['layers'][0]['width'],
            'height': res['layers'][0]['height'],
            'left': res['layers'][0]['bounds'][0],
            'top': res['layers'][0]['bounds'][1],
            'right': res['layers'][0].get('bounds_full', (0, 0, 0, 0))[2],
            'bottom': res['layers'][0].get('bounds_full', (0, 0, 0, 0))[3],
            'style': res['layers'][0].get('style', {}),
            'orientation': res['layers'][0].get('orientation', 'horizontal'),
            'is_rotated': res['layers'][0].get('is_rotated', False),
            'matrix': res['layers'][0].get('matrix', [1,0,0,1,0,0])
        }]
    else:
        print(f"Detectadas {len(res['problems'])} capas con problemas.")
        layer_data = []
        for p in res['problems']:
            bl, bt = p['bounds']
            layer_data.append({
                'name': p['name'],
                'layer_id': p.get('layer_id'),
                'template_layer_id': p.get('template_layer_id'),
                'template_layer_name': p.get('template_layer_name'),
                'width': p['width'],
                'height': p['height'],
                'left': bl,
                'top': bt,
                'right': p.get('bounds_full', (bl, bt, bl + p['width'], bt + p['height']))[2],
                'bottom': p.get('bounds_full', (bl, bt, bl + p['width'], bt + p['height']))[3],
                'style': p.get('style', {}),
                'orientation': p.get('orientation', 'horizontal'),
                'is_rotated': p.get('is_rotated', False),
                'matrix': p.get('matrix', [1,0,0,1,0,0])
            })

    print(f"\n--- 2. Lanzando Fixer (Simulando clic en botón) ---")
    temp_dir = tempfile.gettempdir()
    done_path = os.path.join(temp_dir, "psd_fix_done.txt")
    log_path = os.path.join(temp_dir, "psd_fix_log.txt")
    
    if os.path.exists(done_path): os.remove(done_path)
    if os.path.exists(log_path): os.remove(log_path)

    success = fix_layers_in_psd(psd_path, layer_data)
    if success:
        print("[OK] Comando de lanzamiento enviado con éxito.")
    else:
        print("[ERROR] Falló el lanzamiento del script.")
        return

    print("\n--- 3. Esperando respuesta de Photoshop (60s) ---")
    start = time.time()
    while time.time() - start < 60:
        if os.path.exists(done_path):
            print("[✓] Photoshop ha respondido y terminado.")
            break
        time.sleep(2)
    else:
        print("[✗] TIMEOUT: Photoshop no hizo nada.")
        
    if os.path.exists(log_path):
        print("\n--- LOG DE PHOTOSHOP ---")
        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
            print(f.read())
    else:
        print("\n[!] No se generó ningún log en Photoshop. El script ni siquiera arrancó.")

if __name__ == "__main__":
    test_full_cycle()
