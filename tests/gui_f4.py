import os as _os, subprocess as _sp, shutil as _sh
_shot = (lambda cmd, **k: _sp.run(cmd, **k)) if _sh.which("import") else (lambda *a, **k: None)  # screenshots need ImageMagick (Linux)
import os, subprocess, sys
sys.path.insert(0, sys.argv[1]); import tamer as am; import tkinter as tk
cfg = am.AppConfig(); cfg.data["theme"] = "dark"
while len(cfg.servers) < 3: cfg.servers.append(am.default_server(len(cfg.servers) + 1, cfg.servers))
for s in cfg.servers: s["cluster"] = True
cfg.servers[0]["restart_times"] = "04:00, 16:00"; cfg.save()
root = tk.Tk(); app = am.App(root); errors = []; root.report_callback_exception = lambda *a: errors.append(a)
shot = lambda n: _shot(["import", "-window", "root", "-crop", "1280x820+0+0", os.path.join(sys.argv[2], n)])
tops = lambda: [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]
def close():
    for w in tops(): w.destroy()
def a():
    sf = app.nb.nametowidget(app.nb.tabs()[0]).winfo_children()[0]; sf.canvas.yview_moveto(1.0)
    root.after(700, lambda: (shot("f4_server.png"), b()))
def b(): app._stagger_dialog(); root.after(900, lambda: (shot("f4_stagger.png"), close(), c()))
def c(): app._wipe_dialog(); root.after(900, lambda: (shot("f4_wipe.png"), close(), end()))
def end(): app.mgr.stop_event.set(); root.destroy()
root.after(1500, a); root.mainloop(); print("errors:", errors); assert not errors; print("GUI OK")
