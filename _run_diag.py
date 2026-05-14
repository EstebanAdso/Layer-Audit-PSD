import os
import sys
import time
import tempfile
import subprocess

psd = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else 'textvertical.psd')
jsx = os.path.abspath('_diag.jsx')
done = os.path.join(tempfile.gettempdir(), 'psd_diag_done.txt')
log = os.path.join(tempfile.gettempdir(), 'psd_diag_log.txt')
for p in (done, log):
    if os.path.exists(p):
        os.remove(p)

safe_jsx = jsx.replace('\\', '\\\\')
safe_psd = psd.replace('\\', '\\\\')
vbs = (
    'On Error Resume Next\r\n'
    'Set app = CreateObject("Photoshop.Application")\r\n'
    f'app.Open("{safe_psd}")\r\n'
    'WScript.Sleep 2000\r\n'
    f'app.DoJavaScriptFile("{safe_jsx}")\r\n'
    'Set app = Nothing\r\n'
)
vbs_path = os.path.join(tempfile.gettempdir(), 'diag.vbs')
with open(vbs_path, 'w', encoding='utf-16') as f:
    f.write(vbs)

subprocess.Popen(['cscript', '//Nologo', vbs_path])

start = time.time()
while time.time() - start < 60:
    if os.path.exists(done):
        break
    time.sleep(1)
time.sleep(1)

if os.path.exists(log):
    with open(log, 'r', encoding='utf-8', errors='ignore') as f:
        print(f.read())
else:
    print('NO LOG')
