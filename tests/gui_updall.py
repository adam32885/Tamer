import os as _os, subprocess as _sp, shutil as _sh
_shot = (lambda cmd, **k: _sp.run(cmd, **k)) if _sh.which("import") else (lambda *a, **k: None)  # screenshots need ImageMagick (Linux)
import os, subprocess, sys
sys.path.insert(0, sys.argv[1]); import tamer as am; import tkinter as tk
cfg = am.AppConfig(); cfg.data["theme"] = "dark"
while len(cfg.servers) < 3: cfg.servers.append(am.default_server(len(cfg.servers) + 1, cfg.servers))
cfg.save()
root = tk.Tk(); app = am.App(root); errors = []; root.report_callback_exception = lambda *a: errors.append(a)
def go():
    app._update_all_dialog(); w = app._update_all_win
    tree = [c for c in w.winfo_children()[0].winfo_children() if c.winfo_class() == "Treeview"][0]
    ids = tree.get_children(); tree.set(ids[0], "status", "Done - build 41293817"); tree.set(ids[1], "status", "Waiting for it to come back online (2m 14s)"); tree.set(ids[2], "status", "Waiting for its turn")
    root.after(900, lambda: (_shot(["import", "-window", "root", "-crop", "1280x820+0+0", sys.argv[2] + "/updall.png"]), app.mgr.stop_event.set(), root.destroy()))
root.after(1500, go); root.mainloop(); print("errors:", errors); assert not errors; print("GUI OK")
