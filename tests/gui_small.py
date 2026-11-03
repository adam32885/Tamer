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
def step(i=0):
    if i == 0:
        try:
            server_list_fits()
        except AssertionError as e:  # report it and stop, rather than leaving the window open
            errors.append(e); print("FAILED:", e); app.mgr.stop_event.set(); root.destroy(); return
    if i >= len(names):
        app.mgr.stop_event.set(); root.destroy(); return
    app.nb.select(i)
    root.after(700, lambda: (_shot(["import", "-window", "root", "-crop", f"{W}x{H + 30}+0+0",
                                             os.path.join(out, f"small_{i}.png")]), step(i + 1)))
root.after(1500, step); root.mainloop()
print(names); print("errors:", errors); assert not errors
