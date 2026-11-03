"""File > Settings > General > Text size: Normal / Large / Larger resize everything together - Tk's own fonts,
Tamer's headings, bold labels and logs, the list row height and the Mods tab circles - straight away."""
import sys
sys.path.insert(0, sys.argv[1]); import tamer as am; import tkinter as tk
from tkinter import ttk

cfg = am.AppConfig(); cfg.data.update(theme="dark", text_size="normal", tamer_update_check=False); cfg.save()
am.Manager.ensure_steamcmd = lambda self, s: (_ for _ in ()).throw(RuntimeError("no SteamCMD in tests"))
shown = []
am.messagebox.showinfo = lambda t, m, **k: shown.append(m)
root = tk.Tk(); app = am.App(root); errors = []
root.report_callback_exception = lambda *a: (errors.append(a), __import__("traceback").print_exception(*a), root.destroy())


def sizes():
    f = lambda name: abs(int(am.tkfont.nametofont(name).cget("size")))
    return {"default": f("TkDefaultFont"), "header": f(am.ui_font("Segoe UI", 16, "bold")),
            "log": f(am.ui_font("Consolas", 9)), "row": int(ttk.Style().lookup("Treeview", "rowheight")),
            "circles": app.mod_images[0].height()}


def widgets(w, cls):
    out = [w] if isinstance(w, cls) else []
    for c in w.winfo_children():
        out += widgets(c, cls)
    return out


def a():
    tabs = [app.nb.tab(t, "text") for t in app.nb.tabs()]  # short names, so all ten fit at bigger text sizes
    assert tabs == ["Server", "Launch", "Game", "Mods", "Plugins", "Players", "Schedule", "Messages", "Stats", "Log"], tabs
    normal = sizes()
    assert normal["header"] == 16 and normal["log"] == 9 and normal["row"] == 26 and normal["circles"] == 18, normal
    # through the real Settings window: General > Text size > Larger, Save
    app._settings_dialog(); root.update()
    d = next(w for w in root.winfo_children() if isinstance(w, tk.Toplevel) and w.title() == "Settings")
    box = next(c for c in widgets(d, ttk.Combobox) if c.get() == "Normal")
    assert list(box.cget("values")) == ["Normal", "Large", "Larger"]
    box.set("Larger")
    next(b for b in widgets(d, ttk.Button) if b.cget("text") == "Save").invoke(); root.update()
    big = sizes()
    assert app.cfg.data["text_size"] == "larger" and am.AppConfig().data["text_size"] == "larger"
    assert big["header"] == 20 and big["log"] == 11 and big["default"] > normal["default"], big
    assert big["row"] == round(26 * 1.25) and big["circles"] == round(18 * 1.25), big
    assert shown and "Text size changed" in shown[-1], shown
    # and back down
    app.cfg.data["text_size"] = "large"; am.set_text_scale(am.text_scale_of(app.cfg)); app.apply_theme(); root.update()
    mid = sizes()
    assert normal["header"] < mid["header"] < big["header"] and normal["row"] < mid["row"] < big["row"], mid
    print("text size: Normal", normal, "| Large", mid, "| Larger", big)
    app.mgr.stop_event.set(); root.destroy()


root.after(1500, a); root.mainloop(); print("errors:", errors); assert not errors; print("GUI OK")
