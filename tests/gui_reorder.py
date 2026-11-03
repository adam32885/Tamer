"""Reordering servers: drag and drop, the up/down arrows and Ctrl+Up/Down; nothing happens past the ends; the order
is saved, survives a restart, and Start all goes down the list in that order."""
import os, sys
sys.path.insert(0, sys.argv[1]); import tamer as am; import tkinter as tk
from tkinter import ttk

cfg = am.AppConfig(); cfg.data.update(theme="dark", stagger_starts=True)
cfg.data["servers"] = []
for i, name in enumerate(("Alpha", "Bravo", "Charlie"), 1):
    s = am.default_server(i, cfg.servers); s["name"] = name; cfg.servers.append(s)
cfg.save()
am.Manager.ensure_steamcmd = lambda self, srv: (_ for _ in ()).throw(RuntimeError("no SteamCMD in tests"))
root = tk.Tk(); app = am.App(root); errors = []
root.report_callback_exception = lambda *a: (errors.append(a), __import__("traceback").print_exception(*a), root.destroy())
queued = []
app.mgr.start_staggered = lambda servers, reason="Start all": queued.append([s["name"] for s in servers])


def order():
    return [s["name"] for s in app.cfg.servers]


def shown():
    return [app.tree.item(i, "text") for i in app.tree.get_children()]


def saved():
    return [s["name"] for s in am.AppConfig().servers]


def sid(name):
    return next(s["id"] for s in app.cfg.servers if s["name"] == name)


def arrow(text):
    stack = [app.tree.master]
    while stack:
        w = stack.pop(); stack.extend(w.winfo_children())
        if isinstance(w, ttk.Button) and w.cget("text") == text:
            w.invoke(); root.update(); return
    raise AssertionError(f"no {text} button")


def a():
    assert order() == shown() == ["Alpha", "Bravo", "Charlie"]
    # arrows
    app.tree.selection_set(sid("Charlie")); root.update()
    arrow("▲")
    assert order() == shown() == saved() == ["Alpha", "Charlie", "Bravo"], (order(), shown(), saved())
    assert app.current()["name"] == "Charlie", "stays selected"
    arrow("▲"); arrow("▲")                     # already at the top: nothing happens
    assert order() == ["Charlie", "Alpha", "Bravo"]
    # Ctrl+Down / Ctrl+Up
    app.tree.focus_set(); app.tree.event_generate("<Control-Down>"); root.update()
    assert order() == ["Alpha", "Charlie", "Bravo"], order()
    app.tree.event_generate("<Control-Up>"); root.update()
    assert order() == ["Charlie", "Alpha", "Bravo"], order()
    # drag Charlie (top) down onto Bravo (bottom)
    root.update()
    x, y0, _w, h = app.tree.bbox(sid("Charlie"))
    _x, y2, _w2, _h2 = app.tree.bbox(sid("Bravo"))
    app.tree.event_generate("<ButtonPress-1>", x=x + 10, y=y0 + h // 2); root.update()
    app.tree.event_generate("<B1-Motion>", x=x + 10, y=y2 + h // 2); root.update()
    assert order() == shown() == ["Alpha", "Bravo", "Charlie"], (order(), shown())
    assert saved() == ["Charlie", "Alpha", "Bravo"], "a drag only saves when it's let go"
    app.tree.event_generate("<ButtonRelease-1>", x=x + 10, y=y2 + h // 2); root.update()
    assert saved() == ["Alpha", "Bravo", "Charlie"], saved()
    assert app.current()["name"] == "Charlie" and any("Moved to position 3" in l for l in app.mgr.runtime(sid("Charlie")).log)
    # a click without moving doesn't change anything
    x, y, _w, h = app.tree.bbox(sid("Alpha"))
    app.tree.event_generate("<ButtonPress-1>", x=x + 10, y=y + h // 2)
    app.tree.event_generate("<ButtonRelease-1>", x=x + 10, y=y + h // 2); root.update()
    assert order() == ["Alpha", "Bravo", "Charlie"]
    # Start all follows the list
    app.tree.selection_set(sid("Charlie")); root.update(); arrow("▲"); arrow("▲")
    app._start_all()
    assert queued == [["Charlie", "Alpha", "Bravo"]], queued
    print("reorder: arrows, Ctrl+Up/Down, drag and drop; saved; Start all follows the order")
    # the Server tab: a " in the server name is fine (it reaches ARK as a curly quote); in a password it isn't
    app.tree.selection_set(sid("Alpha")); root.update()
    app.form_vars["session_name"].set('The "Best" Server')
    assert app._save_form(silent=True) and app.current()["session_name"] == 'The "Best" Server'
    app._update_cmd_preview(); root.update()
    assert "SessionName=The “Best” Server" in app.cmd_preview.get("1.0", "end"), app.cmd_preview.get("1.0", "end")
    refused = []  # the normal (not silent) save shows its reason in a box - catch it instead of waiting on a window
    am.messagebox.showerror = lambda t, m, **k: refused.append(m)
    app.form_vars["session_name"].set("Who? Me")
    assert not app._save_form() and "can't contain a ?" in refused[-1], refused
    app.form_vars["session_name"].set("Fine"); app.form_vars["admin_password"].set('pa"ss')
    assert not app._save_form() and "Admin password can't contain" in refused[-1], refused
    app.form_vars["admin_password"].set("GoodPass123")
    assert app._save_form(silent=True) and app.current()["admin_password"] == "GoodPass123"
    print('server names may contain ", passwords may not')
    app.mgr.stop_event.set(); root.destroy()


root.after(1500, a); root.mainloop(); print("errors:", errors); assert not errors; print("GUI OK")
