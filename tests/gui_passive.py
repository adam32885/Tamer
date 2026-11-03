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
def click(mid, passive):                                 # click a mod's real circle in the list
    x, y, _w, h = app.itree.bbox(mid, "#0")
    x += round(app.mod_centres[passive])
    app.itree.event_generate("<ButtonPress-1>", x=x, y=y + h // 2)
    app.itree.event_generate("<ButtonRelease-1>", x=x, y=y + h // 2); root.update()
def shows(mid, passive):
    return str(app.itree.item(mid, "image")[0]) == str(app.mod_images[passive])
def a():
    app.nb.select(app.mods_tab); app._refresh_installed_mods(); root.update()
    assert shows("222", False) and shows("111", False)
    click("222", True)                                   # tick Passive, without selecting the mod first
    s = app.current(); assert s["passive_mods"] == "222" and shows("222", True)
    assert app.itree.selection() == ("222",), "stays selected"
    click("222", True)                                   # clicking the ticked circle keeps it passive
    assert s["passive_mods"] == "222" and shows("222", True)
    assert "-passivemods=222" in app.cmd_preview.get("1.0", "end")
    assert shows("111", False), "other rows unchanged"
    root.after(800, lambda: (_shot(["import", "-window", "root", "-crop", "1280x820+0+0", sys.argv[2] + "/passive.png"]), b()))
def b():
    s = app.current()
    click("222", False)                                  # tick Active
    assert s["passive_mods"] == "" and shows("222", False)
    app._mod_set_passive("333", True); assert s["passive_mods"] == "333"
    app.itree.selection_set("333"); app._mod_remove()
    assert s["mods"] == "111,222" and s["passive_mods"] == "", (s["mods"], s["passive_mods"])
    app.mgr.stop_event.set(); root.destroy()
root.after(1500, a); root.mainloop(); print("errors:", errors); assert not errors; print("GUI OK")
