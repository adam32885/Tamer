import os as _os, subprocess as _sp, shutil as _sh
_shot = (lambda cmd, **k: _sp.run(cmd, **k)) if _sh.which("import") else (lambda *a, **k: None)  # screenshots need ImageMagick (Linux)
import os, subprocess, sys
sys.path.insert(0, sys.argv[1])
import tamer as am
import tkinter as tk
out = sys.argv[2]
cfg = am.AppConfig(); cfg.data["theme"] = "dark"; cfg.save()
am.diagnose_server = lambda m, s: [
    {"severity": "error", "title": "The server ran out of memory", "fix": "ASA needs roughly 12-16 GB of RAM per map. Close other programs, run fewer maps at once, or set a memory-limit restart on the Automation tab.", "evidence": ["[2026.11.02-10.12.01:000][  0]LogMemory: Fatal: Ran out of memory allocating 65536 bytes"]},
    {"severity": "warning", "title": "A mod had trouble downloading or loading", "fix": "Check the mod IDs on the Mods tab. Remove the most recently added mod and start again.", "evidence": ["LogCurseForge: Error: Failed to download mod 123456"]},
    {"severity": "ok", "title": "The server finished starting and is advertising to the server list", "fix": "", "evidence": []}]
am.check_connectivity = lambda m, s: {"verdict": "Something is blocking players - fix the items marked PROBLEM.", "upnp": True, "steps": [
    {"status": "ok", "title": "The server is running and listening on UDP 7777", "detail": ""},
    {"status": "warn", "title": "No firewall rule from this manager", "detail": "Click 'Open firewall port' (or allow ArkAscendedServer.exe / UDP 7777 yourself)."},
    {"status": "ok", "title": "This PC: 192.168.1.20  ·  Internet address: 93.184.216.34", "detail": ""},
    {"status": "ok", "title": "The router has a public internet address", "detail": ""},
    {"status": "fail", "title": "The router isn't forwarding UDP 7777 (as far as UPnP can see)", "detail": "Click 'Open port automatically', or add a port forward in your router's settings: UDP 7777 -> 192.168.1.20."},
    {"status": "unknown", "title": "Not on the public BattleMetrics list yet", "detail": "New servers can take 15-30 minutes to appear."}]}
root = tk.Tk(); app = am.App(root)
errors = []; root.report_callback_exception = lambda *a: errors.append(a)
shot = lambda n: _shot(["import", "-window", "root", os.path.join(out, n)])
def tops(): return [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]
def close():
    for w in tops(): w.destroy()
def a(): app._troubleshoot(); root.after(1200, lambda: (shot("diag.png"), close(), b()))
def b(): app._connectivity(); root.after(1200, lambda: (shot("conn.png"), close(), c()))
def c():
    app._settings_dialog(); root.after(900, lambda: (shot("set_backup.png"), close(), end()))
def end(): app.mgr.stop_event.set(); root.destroy()
root.after(1500, a); root.mainloop()
print("errors:", errors); assert not errors; print("GUI OK")
