"""First-run welcome: shown only when there are no settings yet, checks each step, fills in the starting server and
the servers folder, offers to install; run again from Help it adds a new server instead. Nothing is installed."""
import os, sys, tempfile
sys.path.insert(0, sys.argv[1]); import tamer as am; import tkinter as tk
from tkinter import ttk
for p in (am.CONFIG_PATH,):
    if os.path.exists(p): os.remove(p)                 # a brand-new PC: no settings yet
tmp = tempfile.mkdtemp()
am.roomiest_drive = lambda: (os.path.join(tmp, "ARK Servers"), 500.0)
am.Manager.ensure_steamcmd = lambda self, s: (_ for _ in ()).throw(RuntimeError("no SteamCMD in tests"))
errors_shown = []
am.messagebox.showerror = lambda t, m, **k: errors_shown.append(m)
root = tk.Tk(); app = am.App(root); errors = []
root.report_callback_exception = lambda *a: (errors.append(a), __import__("traceback").print_exception(*a), root.destroy())
installs = []
app._update = lambda validate=False: installs.append(app.current()["id"])


def widgets(w, cls):
    out = [w] if isinstance(w, cls) else []
    for c in w.winfo_children():
        out += widgets(c, cls)
    return out


def page():  # the step showing now
    return next(p for p in app.welcome_win.winfo_children()[0].winfo_children() if p.winfo_ismapped())


def entries():
    return [e for e in widgets(page(), ttk.Entry) if not isinstance(e, ttk.Combobox)]


def press(text):
    next(b for b in widgets(app.welcome_win, ttk.Button) if b.cget("text") == text).invoke(); root.update()


def setv(e, v):
    e.delete(0, "end"); e.insert(0, v)


def a():
    assert app.welcome_win.winfo_exists(), "shown on the first run"
    press("Next")                                       # -> servers folder
    assert entries()[0].get() == os.path.join(tmp, "ARK Servers"), "suggests the roomiest drive"
    setv(entries()[0], "relative\\path"); press("Next")
    assert "full folder path" in errors_shown[-1], errors_shown
    setv(entries()[0], os.path.join(tmp, "My Servers")); press("Next")   # -> your server
    name, players, pw = entries()
    setv(name, ""); press("Next"); assert "name" in errors_shown[-1]
    setv(name, "Island PvE"); setv(players, "500"); press("Next"); assert "1 to 255" in errors_shown[-1]
    setv(players, "50"); setv(pw, "letmein")
    widgets(page(), ttk.Combobox)[0].set("Ragnarok")
    press("Next")                                       # -> ports
    gp, rp = entries()
    setv(rp, gp.get()); press("Next"); assert "must be different" in errors_shown[-1]
    setv(gp, "7779"); setv(rp, "27022")
    press("Back"); press("Next")                         # Back keeps what was typed
    assert entries()[0].get() == "7779"
    press("Next")                                       # -> all set
    assert "Island PvE" in widgets(page(), ttk.Label)[2].cget("text")
    press("Finish")
    s = app.cfg.servers[0]
    assert len(app.cfg.servers) == 1, "filled in the starting server"
    assert (s["name"], s["session_name"], s["map"], s["max_players"], s["server_password"], s["port"], s["rcon_port"]) == \
        ("Island PvE", "Island PvE", "Ragnarok_WP", 50, "letmein", 7779, 27022), s
    assert s["install_dir"] == os.path.join(tmp, "My Servers", "Island_PvE"), s["install_dir"]
    assert app.cfg.data["servers_dir"] == os.path.join(tmp, "My Servers") and os.path.isdir(app.cfg.data["servers_dir"])
    assert installs == [s["id"]], "offered install runs"
    assert am.AppConfig().servers[0]["name"] == "Island PvE", "saved"
    app._add_server()                                   # new servers go in the chosen folder too
    assert app.cfg.servers[-1]["install_dir"].startswith(os.path.join(tmp, "My Servers")), app.cfg.servers[-1]
    root.after(300, b)


def b():
    count = len(app.cfg.servers)
    app._welcome(); root.update()                       # Help > Run the welcome again, then Skip
    press("Skip")
    assert len(app.cfg.servers) == count and app.cfg.servers[0]["name"] == "Island PvE", "Skip changes nothing"
    app._welcome(); root.update()                       # run again and finish: adds a server, the first is untouched
    for _ in range(4):
        press("Next")
    press("Finish")
    assert len(app.cfg.servers) == count + 1 and app.cfg.servers[0]["name"] == "Island PvE"
    new = app.cfg.servers[-1]
    assert new["port"] not in (7779,) and new["install_dir"].startswith(os.path.join(tmp, "My Servers")), new
    app.mgr.stop_event.set(); root.destroy()


root.after(2000, a); root.mainloop(); print("errors:", errors); assert not errors; print("GUI OK")
