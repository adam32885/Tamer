import os as _os, subprocess as _sp, shutil as _sh
_shot = (lambda cmd, **k: _sp.run(cmd, **k)) if _sh.which("import") else (lambda *a, **k: None)  # screenshots need ImageMagick (Linux)
import os, subprocess, sys
sys.path.insert(0, sys.argv[1]); import tamer as am; import tkinter as tk
cfg = am.AppConfig(); cfg.data["theme"] = "dark"; s0 = cfg.servers[0]; s0["mods"] = "111,222,333"
cfg.data["mod_cache"] = {"111": {"id": "111", "name": "Super Structures", "updated": "2026-10-30"},
                         "222": {"id": "222", "name": "Love Ascended (event)", "updated": "2026-02-19"},
                         "333": {"id": "333", "name": "Awesome Spyglass", "updated": "2026-10-12"}}
cfg.save()
m = am.Manager(cfg, lambda *a: None)
s0["passive_mods"] = "222"
cl = m.to_cmdline(m.build_command(s0)); print(cl[cl.index("-mods"):].split(" -clusterid")[0])
assert "-mods=222,111,333" in cl and "-passivemods=222" in cl
s0["passive_mods"] = "999"; assert "-passivemods" not in m.to_cmdline(m.build_command(s0)), "stale passive ID ignored"
s0["passive_mods"] = ""; cfg.save()
root = tk.Tk(); app = am.App(root); errors = []; root.report_callback_exception = lambda *a: (errors.append(a), __import__("traceback").print_exception(*a), root.destroy())
am.messagebox.askyesno = lambda *a, **k: True; am.messagebox.showinfo = lambda *a, **k: None
def a():
    app.nb.select(app.mods_tab); app._refresh_installed_mods()
    assert app.mod_passive_chk.instate(["disabled"]), "disabled with no selection"
    app.itree.selection_set("222"); root.update()
    assert app.mod_active_var.get() and not app.mod_passive_var.get()
    app.mod_passive_chk.invoke(); root.update()          # tick Passive
    s = app.current(); assert s["passive_mods"] == "222" and app.itree.set("222", "mode") == "Passive"
    assert app.mod_passive_var.get() and not app.mod_active_var.get(), "boxes are exclusive"
    app.mod_passive_chk.invoke(); root.update()          # unticking the ticked box keeps it passive
    assert s["passive_mods"] == "222" and app.mod_passive_var.get()
    assert "-passivemods=222" in app.cmd_preview.get("1.0", "end")
    app.itree.selection_set("111"); root.update()
    assert app.mod_active_var.get() and not app.mod_passive_var.get(), "follows selection"
    app.itree.selection_set("222"); root.update()
    root.after(800, lambda: (_shot(["import", "-window", "root", "-crop", "1280x820+0+0", sys.argv[2] + "/passive.png"]), b()))
def b():
    s = app.current()
    app.mod_active_chk.invoke(); root.update()           # tick Active
    assert s["passive_mods"] == "" and app.itree.set("222", "mode") == "Active"
    app._mod_set_passive("333", True); assert s["passive_mods"] == "333"
    app.itree.selection_set("333"); app._mod_remove()
    assert s["mods"] == "111,222" and s["passive_mods"] == "", (s["mods"], s["passive_mods"])
    assert app.mod_active_chk.instate(["disabled"])
    app.mgr.stop_event.set(); root.destroy()
root.after(1500, a); root.mainloop(); print("errors:", errors); assert not errors; print("GUI OK")
