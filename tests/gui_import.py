"""File > Import existing server: from a (pretend) running server and from a folder; the preview, the name,
the cluster ID question, and replacing the welcome's empty starter server."""
import os, sys, tempfile
sys.path.insert(0, sys.argv[1]); import tamer as am; import tkinter as tk
from tkinter import ttk
tmp = tempfile.mkdtemp()


def make_server(root, gus=""):
    exe = os.path.join(root, am.SERVER_EXE_REL)
    os.makedirs(os.path.dirname(exe), exist_ok=True); open(exe, "w").close()
    os.makedirs(os.path.join(root, am.CONFIG_REL), exist_ok=True)
    open(os.path.join(root, am.CONFIG_REL, "GameUserSettings.ini"), "w").write(gus)
    return exe


exe1 = make_server(os.path.join(tmp, "Running One"))
make_server(os.path.join(tmp, "Folder Two"), "[SessionSettings]\nSessionName=Folder Two\nPort=7801\n"
                                              "[ServerSettings]\nRCONPort=27060\n")
LINE = (f'"{exe1}" "Ragnarok_WP?listen?SessionName=Running One?Port=7799?RCONPort=27055?ServerAdminPassword=p" '
        '-mods=111,222 -clusterid=theirs -ClusterDirOverride=D:\\TheirCluster -servergamelog')
am.scan_server_processes = lambda: [(999999, exe1, LINE)]
cfg = am.AppConfig(); cfg.data.update(theme="dark", cluster_id="mine"); cfg.save()
am.Manager.ensure_steamcmd = lambda self, s: (_ for _ in ()).throw(RuntimeError("no SteamCMD in tests"))
shown, asked = [], []
am.messagebox.showinfo = lambda t, m, **k: shown.append(m)
am.messagebox.showerror = lambda t, m, **k: shown.append("ERROR " + m)
am.messagebox.askyesnocancel = lambda t, m, **k: asked.append(m) or True
root = tk.Tk(); app = am.App(root); errors = []
root.report_callback_exception = lambda *a: (errors.append(a), __import__("traceback").print_exception(*a), root.destroy())
app.mgr.adopt_processes = lambda: None  # the pretend process isn't real


def widgets(w, cls):
    out = [w] if isinstance(w, cls) else []
    for c in w.winfo_children():
        out += widgets(c, cls)
    return out


def press(text):
    next(b for b in widgets(app.import_win, ttk.Button) if b.cget("text") == text).invoke(); root.update()


def after(cond, then, tries=60):
    root.update()
    if cond(): then()
    elif tries: root.after(100, lambda: after(cond, then, tries - 1))
    else: raise SystemExit(f"timed out before {then.__name__}")


def preview():
    return widgets(app.import_win, tk.Text)[0].get("1.0", "end")


def a():
    app._import_dialog()
    procs = widgets(app.import_win, ttk.Treeview)[0]
    after(lambda: "999999" in procs.get_children(), b)


def b():
    count = len(app.cfg.servers)
    press("Read its settings")
    text = preview()
    for bit in ("Map: Ragnarok (Ragnarok_WP)", "game 7799, RCON 27055", "Mods: 2: 111, 222", "Cluster: yes (ID theirs)",
                "Admin password: found (hidden)", "Flags: -servergamelog"):
        assert bit in text, (bit, text)
    assert "ServerAdminPassword" not in text and "=p" not in text, "passwords never shown"
    name = [e for e in widgets(app.import_win, ttk.Entry) if e.get() == "Running One"][0]
    name.delete(0, "end"); name.insert(0, "Rag (imported)")
    press("Import")
    s = app.cfg.servers[-1]
    assert len(app.cfg.servers) == count + 1 and s["name"] == "Rag (imported)" and s["session_name"] == "Running One"
    assert s["install_dir"] == os.path.join(tmp, "Running One") and s["mods"] == "111,222" and s["cluster"]
    assert asked and "cluster ID 'theirs'" in asked[-1], asked
    assert app.cfg.data["cluster_id"] == "theirs" and app.cfg.data["cluster_dir"] == "D:\\TheirCluster"
    assert app.current()["id"] == s["id"] and shown and "is imported" in shown[-1], shown
    # the same folder again: refused
    app._import_dialog(); root.update()
    after(lambda: True, c)


def c():
    procs = widgets(app.import_win, ttk.Treeview)[0]
    after(lambda: "none" in procs.get_children(), d)  # the imported server isn't offered again


def d():
    shown.clear()
    radios = widgets(app.import_win, ttk.Radiobutton)
    radios[2].invoke()                                  # "Just its folder"
    entries = [e for e in widgets(app.import_win, ttk.Entry)]
    entries[1].insert(0, os.path.join(tmp, "Running One")); press("Read its settings")
    assert shown and "already manages" in shown[-1], shown
    entries[1].delete(0, "end"); entries[1].insert(0, os.path.join(tmp, "Folder Two")); press("Read its settings")
    assert "game 7801, RCON 27060" in preview() and "folder only" in preview(), preview()
    app.import_win.destroy()
    # from the welcome: the empty starter server is replaced, not left behind
    starter = am.default_server(9, app.cfg.servers); app.cfg.servers.append(starter)
    count = len(app.cfg.servers)
    app._import_dialog(replace=starter); root.update()
    widgets(app.import_win, ttk.Radiobutton)[2].invoke()
    e = [x for x in widgets(app.import_win, ttk.Entry)][1]
    e.insert(0, os.path.join(tmp, "Folder Two")); press("Read its settings"); press("Import")
    assert len(app.cfg.servers) == count and starter not in app.cfg.servers, "starter replaced"
    assert app.cfg.servers[-1]["name"] == "Folder Two"
    app.mgr.stop_event.set(); root.destroy()


root.after(1500, a); root.mainloop(); print("errors:", errors); assert not errors; print("GUI OK")
