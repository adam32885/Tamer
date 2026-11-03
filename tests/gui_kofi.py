"""The Ko-fi link in the top-right corner and in the Help menu opens the Ko-fi page, and follows the theme."""
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
    app.cfg.data["theme"] = "light"; app.apply_theme(); root.update()
    assert str(link.cget("foreground")) == am.THEMES["light"]["accent"], "follows a live theme switch"
    app.mgr.stop_event.set(); root.destroy()


root.after(1500, a); root.mainloop(); print("errors:", errors); assert not errors; print("GUI OK")
