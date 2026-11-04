"""The Ko-fi and Discord links in the top-right corner and in the Help menu open their pages, and follow the theme."""
import sys
sys.path.insert(0, sys.argv[1]); import tamer as am; import tkinter as tk
cfg = am.AppConfig(); cfg.data["theme"] = "dark"; cfg.save()
am.Manager.ensure_steamcmd = lambda self, s: (_ for _ in ()).throw(RuntimeError("no SteamCMD in tests"))
opened = []
am.webbrowser.open = opened.append                       # never open a real browser in tests
root = tk.Tk(); app = am.App(root); errors = []
root.report_callback_exception = lambda *a: (errors.append(a), __import__("traceback").print_exception(*a), root.destroy())


def a():
    link = app.kofi_link
    assert link.cget("text") == "☕ Support Tamer"
    assert link.winfo_ismapped() and link.winfo_rootx() > app.menubar.winfo_rootx() + app.menubar.winfo_width() // 2, \
        "shown, on the right of the bar"
    assert str(link.cget("foreground")) == am.THEMES["dark"]["accent"], link.cget("foreground")
    link.event_generate("<Enter>"); root.update()
    assert "underline" in str(link.cget("font")), "underlined on hover"
    link.event_generate("<Leave>"); link.event_generate("<Button-1>"); root.update()
    assert opened == [am.KOFI_URL] == ["https://ko-fi.com/tamerarkmanager"], opened
    hm = app.menubar.winfo_children()[1].nametowidget(app.menubar.winfo_children()[1].cget("menu"))
    labels = [hm.entrycget(i, "label") for i in range(hm.index("end") + 1) if hm.type(i) == "command"]
    hm.invoke(labels.index("Support Tamer on Ko-fi"))
    assert opened[-1] == am.KOFI_URL, opened
    # the Discord link sits right under the Ko-fi one, and below it in the Help menu
    dc = app.discord_link
    assert dc.cget("text") == "💬 Get help on Discord"
    assert dc.winfo_ismapped() and dc.winfo_rooty() > link.winfo_rooty(), "under the Ko-fi link"
    assert dc.winfo_rootx() + dc.winfo_width() == link.winfo_rootx() + link.winfo_width(), "right edges line up"
    assert str(dc.cget("foreground")) == am.THEMES["dark"]["accent"], dc.cget("foreground")
    dc.event_generate("<Enter>"); root.update()
    assert "underline" in str(dc.cget("font")), "underlined on hover"
    dc.event_generate("<Leave>"); dc.event_generate("<Button-1>"); root.update()
    assert opened[-1] == am.DISCORD_URL == "https://discord.gg/nj7tkY53gq", opened
    assert labels.index("Get help on Discord") == labels.index("Support Tamer on Ko-fi") + 1, labels
    opened.clear(); hm.invoke(labels.index("Get help on Discord"))
    assert opened == [am.DISCORD_URL], opened
    app.cfg.data["theme"] = "light"; app.apply_theme(); root.update()
    assert str(link.cget("foreground")) == am.THEMES["light"]["accent"], "follows a live theme switch"
    assert str(dc.cget("foreground")) == am.THEMES["light"]["accent"], "follows a live theme switch"
    assert str(dc.master.cget("background")) == am.THEMES["light"]["bg"], "the links' frame matches the bar"
    app.mgr.stop_event.set(); root.destroy()


root.after(1500, a); root.mainloop(); print("errors:", errors); assert not errors; print("GUI OK")
