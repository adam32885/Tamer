import os as _os, subprocess as _sp, shutil as _sh
_shot = (lambda cmd, **k: _sp.run(cmd, **k)) if _sh.which("import") else (lambda *a, **k: None)  # screenshots need ImageMagick (Linux)
import math, os, random, subprocess, sys, time
sys.path.insert(0, sys.argv[1])
import tamer as am
import tkinter as tk
out = sys.argv[2]
cfg = am.AppConfig(); cfg.data["theme"] = "dark"
s0 = cfg.servers[0]; s0["mods"] = "928988"; s0["timed_tasks"] = am.example_tasks(); cfg.save()
root = tk.Tk()
app = am.App(root)
errors = []
root.report_callback_exception = lambda *a: errors.append(a)
s = app.cfg.servers[0]; rt = app.mgr.runtime(s["id"]); s["ram_restart_gb"] = 20
now = time.time(); random.seed(1)
for i in range(600):
    rt.history.append((now - 3000 + i * 5, 18 + 10 * math.sin(i / 40) ** 2 + random.random() * 4, (11 + i / 100) * 1024 ** 3))
app.mgr.sys_mem = (40 * 1024 ** 3, 64 * 1024 ** 3)
app.mgr.log(s, "Server is online (RCON responding)."); app.mgr.log(s, "Player joined: Alice")
shot = lambda n: _shot(["import", "-window", "root", os.path.join(out, n)])
seq = [(0, "dark_server.png"), (1, "dark_game.png"), (5, "dark_tasks.png"), (6, "dark_perf.png")]
def step(i=0):
    if i < len(seq):
        app.nb.select(seq[i][0]); root.after(800, lambda: (shot(seq[i][1]), step(i + 1)))
    else:
        app._settings_dialog(); root.after(900, lambda: (shot("dark_settings.png"), light()))
def light():
    for w in root.winfo_children():
        if isinstance(w, tk.Toplevel): w.destroy()
    app.cfg.data["theme"] = "light"; app.apply_theme(); app.nb.select(6)
    root.after(800, lambda: (shot("light_perf.png"), back_dark()))
def back_dark():
    app.cfg.data["theme"] = "dark"; app.apply_theme(); app.nb.select(2)
    root.after(800, lambda: (shot("dark_mods.png"), end()))
def end():
    app.mgr.stop_event.set(); root.destroy()
root.after(1500, step)
root.mainloop()
print("errors:", errors); assert not errors; print("GUI OK")
