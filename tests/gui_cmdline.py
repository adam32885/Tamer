import os as _os, subprocess as _sp, shutil as _sh
_shot = (lambda cmd, **k: _sp.run(cmd, **k)) if _sh.which("import") else (lambda *a, **k: None)  # screenshots need ImageMagick (Linux)
import os, subprocess, sys
sys.path.insert(0, sys.argv[1]); import tamer as am; import tkinter as tk
cfg = am.AppConfig(); cfg.data["theme"] = sys.argv[3] if len(sys.argv) > 3 else "dark"; cfg.servers[0]["cluster"] = True; cfg.save()
root = tk.Tk(); app = am.App(root); errors = []; root.report_callback_exception = lambda *a: errors.append(a)
shot = lambda n: _shot(["import", "-window", "root", "-crop", "1280x820+0+0", os.path.join(sys.argv[2], n)])
def a():
    app.nb.select(app.cmd_tab)
    app.cmd_platform.set("ALL"); app.cmd_vars["-exclusivejoin"].set(True); app.cmd_vars["-NoWildBabies"].set(True)
    app.cmd_culture.set("en"); app.cmd_priority.set("Above normal"); app.cmd_cores = [0, 1]
    root.after(900, lambda: (shot("cmd_top.png"), b()))
def b():
    assert "-ServerPlatform=ALL" in app.cmd_preview2.get("1.0", "end") and "-exclusivejoin" in app.cmd_preview2.get("1.0", "end")
    app.cmd_public_ip.set("not-an-ip")
    import tkinter.messagebox as mb; msgs = []; mb.showerror = lambda *x, **k: msgs.append(x[1])
    am.messagebox.showerror = lambda *x, **k: msgs.append(x[1])
    assert app._save_form() is False and "isn't a valid IP" in msgs[0], msgs
    app.cmd_public_ip.set("")
    assert app._save_form() is True
    s = app.current(); print({k: s[k] for k in ("server_platform", "culture", "cpu_priority", "cpu_cores")}, s["cmd_flags"])
    assert s["server_platform"] == "ALL" and "-exclusivejoin" in s["cmd_flags"] and s["cpu_cores"] == [0, 1]
    sf = app.cmd_tab.winfo_children()[0]; sf.canvas.yview_moveto(0.55)
    root.after(700, lambda: (shot("cmd_mid.png"), c()))
def c(): app._cores_dialog(); root.after(800, lambda: (shot("cmd_cores.png"), [w.destroy() for w in root.winfo_children() if isinstance(w, tk.Toplevel)], end()))
def end(): app.mgr.stop_event.set(); root.destroy()
root.after(1500, a); root.mainloop(); print("errors:", errors); assert not errors; print("GUI OK")
