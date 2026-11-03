import os as _os, subprocess as _sp, shutil as _sh
_shot = (lambda cmd, **k: _sp.run(cmd, **k)) if _sh.which("import") else (lambda *a, **k: None)  # screenshots need ImageMagick (Linux)
import os, subprocess, sys, zipfile
sys.path.insert(0, sys.argv[1]); import tamer as am; import tkinter as tk
cfg = am.AppConfig(); cfg.data["theme"] = "dark"; s = cfg.servers[0]; cfg.save()
p = am.asaapi_paths(s); os.makedirs(os.path.join(p["plugins"]), exist_ok=True)
open(p["loader"], "w").write("x"); os.makedirs(p["api_dir"], exist_ok=True); open(p["dll"], "w").write("x")
am.write_json_file(p["manifest"], {"version": "1.21", "files": []})
for name, info in (("ArkShop", {"FullName": "Ark Shop", "Version": 1.5, "Description": "Points shop and kits"}),
                   ("Permissions", {"FullName": "Permissions", "Version": 1.03, "Description": "Groups and permissions for other plugins"}),
                   ("DiscordBridge", {})):
    d = os.path.join(p["plugins"], name); os.makedirs(d, exist_ok=True); open(os.path.join(d, name + ".dll"), "w").write("x")
    if info: am.write_json_file(os.path.join(d, "PluginInfo.json"), info); open(os.path.join(d, "config.json"), "w").write("{}")
am.set_plugin_enabled(s, "DiscordBridge", False)
root = tk.Tk(); app = am.App(root); errors = []; root.report_callback_exception = lambda *a: errors.append(a)
opened, infos = [], []
am.open_path = opened.append; am.messagebox.showinfo = lambda *a, **k: infos.append(a)
def button(text):
    stack = [app.plugins_tab]
    while stack:
        w = stack.pop(); stack.extend(w.winfo_children())
        if isinstance(w, am.ttk.Button) and w.cget("text") == text:
            return w
    raise AssertionError(f"no {text!r} button")
def a():
    app.nb.select(app.plugins_tab); app._api_latest_tag = "1.22"; app._refresh_plugins()
    button("Plugins folder").invoke(); assert opened == [p["plugins"]], opened
    os.rename(p["plugins"], p["plugins"] + "_x"); button("Plugins folder").invoke()
    os.rename(p["plugins"] + "_x", p["plugins"])
    assert opened == [p["plugins"]] and "Install AsaApi first" in infos[-1][1], infos
    root.after(900, lambda: (_shot(["import", "-window", "root", "-crop", "1280x820+0+0", sys.argv[2] + "/plugins.png"]), app.mgr.stop_event.set(), root.destroy()))
root.after(1500, a); root.mainloop(); print("errors:", errors); assert not errors; print("GUI OK")
