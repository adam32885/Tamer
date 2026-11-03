"""File > Tamer Chat window: saving writes the bot's .env and servers.json; Plugins > Install Tamer Chat explains
when the plugin isn't built. The bot is never started here."""
import json, os, sys
sys.path.insert(0, sys.argv[1]); import tamer as am; import tkinter as tk
from tkinter import ttk
bot = os.path.join(sys.argv[1], "Tamer_Chat"); os.makedirs(bot, exist_ok=True)  # the default folder, next to Tamer
open(os.path.join(bot, "tamer_chat.py"), "w").write("raise SystemExit('the GUI test must not start the bot')\n")
open(os.path.join(bot, ".env.example"), "w").write("DISCORD_TOKEN=\nBRIDGE_CHANNEL_ID=\n# keep me\nPOLL_SECONDS=2\n")
cfg = am.AppConfig(); cfg.data["theme"] = "dark"; cfg.save()
am.Manager.ensure_steamcmd = lambda self, s: (_ for _ in ()).throw(RuntimeError("no SteamCMD in tests"))
root = tk.Tk(); app = am.App(root); errors = []
root.report_callback_exception = lambda *a: (errors.append(a), __import__("traceback").print_exception(*a), root.destroy())
shown = []
am.messagebox.showinfo = lambda *a, **k: shown.append(("info", a[1]))
am.messagebox.showerror = lambda *a, **k: shown.append(("error", a[1]))


def widgets(w, cls):
    out = [w] if isinstance(w, cls) else []
    for c in w.winfo_children():
        out += widgets(c, cls)
    return out


def button(w, text):
    return next(b for b in widgets(w, ttk.Button) if b.cget("text") == text)


def a():
    app._chat_dialog(); root.update()
    d = app.chat_win
    entries = widgets(d, ttk.Entry)                      # folder, token, 4 IDs, Python
    assert len(entries) == 7, len(entries)
    assert entries[0].get() == bot and entries[1].cget("show") == "•", "default folder; token hidden"
    entries[1].insert(0, "secret-token"); entries[2].insert(0, "not a number")
    button(d, "Save").invoke(); root.update()
    assert shown and shown[-1][0] == "error" and "should be a number" in shown[-1][1], shown
    entries[2].delete(0, "end"); entries[2].insert(0, "1234567890")
    button(d, "Save").invoke(); root.update()
    env = am.env_read(os.path.join(bot, ".env"))
    assert env["DISCORD_TOKEN"] == "secret-token" and env["BRIDGE_CHANNEL_ID"] == "1234567890", env
    assert env["BRIDGE_KEY"] == app.cfg.data["chat_key"] and env["POLL_SECONDS"] == "2"
    assert app.cfg.data["chat_dir"] == "" and not app.cfg.data["chat_run"], "default folder stored as blank"
    names = [x["name"] for x in json.load(open(os.path.join(bot, "servers.json")))]
    assert names == [x["name"] for x in app.cfg.servers], names
    assert "secret-token" not in open(am.chat_log_path(), encoding="utf-8").read() if os.path.exists(am.chat_log_path()) else True
    root.after(2500, b)                                  # let the window refresh its status once


def b():
    d = app.chat_win
    assert any(l.cget("text") == "Bot stopped" for l in widgets(d, ttk.Label)), "status shown"
    shown.clear()
    app.nb.select(app.plugins_tab); root.update()
    button(app.plugins_tab, "Install Tamer Chat").invoke()
    assert shown and "hasn't been built yet" in shown[-1][1], shown
    d.destroy(); app.mgr.stop_event.set(); root.destroy()


root.after(1500, a); root.mainloop(); print("errors:", errors); assert not errors; print("GUI OK")
