"""Removing every server and reopening Tamer: the list stays empty (no blank "Server 1"), the welcome opens,
Skip keeps it empty, Finish adds exactly one. A brand-new Tamer still gets its starter server."""
import os, sys, tempfile
sys.path.insert(0, sys.argv[1]); import tamer as am; import tkinter as tk
from tkinter import ttk
tmp = tempfile.mkdtemp()
am.roomiest_drive = lambda: (os.path.join(tmp, "ARK Servers"), 500.0)
am.Manager.ensure_steamcmd = lambda self, s: (_ for _ in ()).throw(RuntimeError("no SteamCMD in tests"))
am.messagebox.askyesno = lambda *a, **k: True
am.messagebox.showerror = lambda *a, **k: None

if os.path.exists(am.CONFIG_PATH):
    os.remove(am.CONFIG_PATH)
first = am.AppConfig()                                    # brand new: a starter server for the welcome
assert len(first.servers) == 1 and first.first_run
first.data["servers"] = []; first.data["theme"] = "dark"; first.save()   # someone removed them all
again = am.AppConfig()
assert again.servers == [] and not again.first_run, "an empty list stays empty - no blank profile"
print("settings with no servers load with no servers")

root = tk.Tk(); app = am.App(root); errors = []
root.report_callback_exception = lambda *a: (errors.append(a), __import__("traceback").print_exception(*a), root.destroy())
installs = []
app._update = lambda validate=False: installs.append(1)


def widgets(w, cls):
    out = [w] if isinstance(w, cls) else []
    for c in w.winfo_children():
        out += widgets(c, cls)
    return out


def press(text):
    next(b for b in widgets(app.welcome_win, ttk.Button) if b.cget("text") == text).invoke(); root.update()


def a():
    assert getattr(app, "welcome_win", None) is not None and app.welcome_win.winfo_exists(), "welcome opens"
    assert app.h_name.cget("text") == "No server selected"
    press("Skip")
    assert app.cfg.servers == [] and am.AppConfig().servers == [], "Skip keeps it empty"
    app._welcome(); root.update()                        # set one up after all
    for _ in range(4):
        press("Next")
    press("Finish")
    assert len(app.cfg.servers) == 1 and installs == [1], app.cfg.servers
    assert app.cfg.servers[0]["install_dir"].startswith(os.path.join(tmp, "ARK Servers"))
    app._remove_server(); root.update()                  # and remove it again: still nothing made behind our back
    assert app.cfg.servers == [] and am.AppConfig().servers == []
    print("welcome opens; Skip keeps it empty; Finish adds one; removing it leaves it empty")
    app.mgr.stop_event.set(); root.destroy()


root.after(2000, a); root.mainloop(); print("errors:", errors); assert not errors; print("GUI OK")
