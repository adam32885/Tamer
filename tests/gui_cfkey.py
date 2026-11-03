import os as _os, subprocess as _sp, shutil as _sh
_shot = (lambda cmd, **k: _sp.run(cmd, **k)) if _sh.which("import") else (lambda *a, **k: None)  # screenshots need ImageMagick (Linux)
import os, subprocess, sys
sys.path.insert(0, sys.argv[1]); import tamer as am; import tkinter as tk
cfg = am.AppConfig(); cfg.data["theme"] = "dark"; cfg.data["curseforge_api_key"] = ' "$2a$10$abc" '; cfg.save()
root = tk.Tk(); app = am.App(root); errors = []; root.report_callback_exception = lambda *a: errors.append(a)
def a():
    app._settings_dialog()
    root.after(900, lambda: (_shot(["import", "-window", "root", sys.argv[2] + "/settings_key.png"]), b()))
def b():
    d = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)][0]
    btns = []
    def walk(w):
        for c in w.winfo_children():
            if c.winfo_class() == "TButton": btns.append(c.cget("text"))
            walk(c)
    walk(d); assert "Test key" in btns, btns
    app.mgr.stop_event.set(); root.destroy()
root.after(1500, a); root.mainloop(); print("errors:", errors); assert not errors; print("GUI OK")
