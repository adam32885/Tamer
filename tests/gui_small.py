import os as _os, subprocess as _sp, shutil as _sh
_shot = (lambda cmd, **k: _sp.run(cmd, **k)) if _sh.which("import") else (lambda *a, **k: None)  # screenshots need ImageMagick (Linux)
"""Screenshot every tab at a non-maximized size with 125% display scaling."""
import os, subprocess, sys, time, math
sys.path.insert(0, sys.argv[1])
import tamer as am
import tkinter as tk
out, W, H, SCALE = sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), float(sys.argv[5])
cfg = am.AppConfig(); s0 = cfg.servers[0]; s0["timed_tasks"] = am.example_tasks(); s0["mods"] = "1,2,3"
cfg.data["theme"] = "light"; cfg.save()
root = tk.Tk()
root.tk.call("tk", "scaling", 1.333 * SCALE)
app = am.App(root)
root.geometry(f"{W}x{H}+0+0")
errors = []; root.report_callback_exception = lambda *a: errors.append(a)
for i in range(3):
    app.mgr.log(s0, f"log line {i}")
names = [app.nb.tab(i, "text") for i in app.nb.tabs()]
def server_list_fits():
    """Status and Players are never cut off, and the server list leaves the tab names room to show in full."""
    font = am.tkfont.nametofont("TkDefaultFont")
    for col, texts in (("status", ["Status", "Not installed", "Queued to start"]), ("players", ["Players"])):
        need = max(font.measure(t) for t in texts) + 8
        assert app.tree.column(col, "width") >= need, (col, app.tree.column(col, "width"), need)
    total = sum(app.tree.column(c, "width") for c in ("#0", "map", "status", "players"))
    tabs = sum(font.measure(app.nb.tab(t, "text")) + 20 for t in app.nb.tabs())
    assert app.nb.winfo_width() >= tabs, ("tab names cut off", app.nb.winfo_width(), tabs)
    print("server list:", app.tree.winfo_width(), "px wide (columns need", total, ") | tabs:", app.nb.winfo_width(),
          "px for", tabs)
def installed_rows():
    """How many mods the Mods tab's installed list shows without scrolling (filled with 20 pretend rows)."""
    app.nb.select(names.index("Mods")); root.update()
    t = app.itree; old = t.get_children(); t.detach(*old)
    rows = [t.insert("", "end", text="", values=(f"Mod {n}", str(n), "2026-01-01")) for n in range(20)]
    root.update()
    top = next((y for y in range(t.winfo_height()) if t.identify_row(y)), None)  # where the first row starts
    rh = int(am.ttk.Style().lookup("Treeview", "rowheight"))
    shown = 0 if top is None else (t.winfo_height() - top) // rh  # whole rows only
    t.delete(*rows)
    for n, r in enumerate(old):
        t.reattach(r, "", n)
    return shown
def mods_list_fits():
    """The installed mods list (the whole right column) isn't squeezed to a row or two: on a laptop-size window
    (1366x768) at least 8 show at Large (the default) and 6 at Larger, on the tiny test window (1100x700 at 125%) 3 and 2."""
    large = installed_rows()
    am.set_text_scale(1.25); app.apply_theme(); root.update()
    larger = installed_rows()
    am.set_text_scale(am.text_scale_of(app.cfg)); app.apply_theme(); root.update()
    print("installed mods shown: Large", large, "| Larger", larger)
    need = (8, 6) if W >= 1366 and SCALE <= 1 else (3, 2)
    assert large >= need[0] and larger >= need[1], ("installed mods list squeezed", large, larger, "need", need)
def step(i=0):
    if i == 0:
        try:
            server_list_fits()
            mods_list_fits()
        except AssertionError as e:  # report it and stop, rather than leaving the window open
            errors.append(e); print("FAILED:", e); app.mgr.stop_event.set(); root.destroy(); return
    if i >= len(names):
        app.mgr.stop_event.set(); root.destroy(); return
    app.nb.select(i)
    root.after(700, lambda: (_shot(["import", "-window", "root", "-crop", f"{W}x{H + 30}+0+0",
                                             os.path.join(out, f"small_{i}.png")]), step(i + 1)))
root.after(1500, step); root.mainloop()
print(names); print("errors:", errors); assert not errors
