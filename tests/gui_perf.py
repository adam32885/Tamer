import os as _os, subprocess as _sp, shutil as _sh
_shot = (lambda cmd, **k: _sp.run(cmd, **k)) if _sh.which("import") else (lambda *a, **k: None)  # screenshots need ImageMagick (Linux)
import math, os, random, subprocess, sys, time
sys.path.insert(0, sys.argv[1])
import tamer as am
import tkinter as tk

out = sys.argv[2]
root = tk.Tk()
app = am.App(root)
errors = []
root.report_callback_exception = lambda *a: errors.append(a)
s = app.cfg.servers[0]
s["ram_restart_gb"] = 20
rt = app.mgr.runtime(s["id"])
now = time.time()
random.seed(3)
for i in range(600):
    t = now - 3000 + i * 5
    if 300 <= i < 330:
        continue  # gap: server restarted
    rt.history.append((t, 18 + 12 * math.sin(i / 40) ** 2 + random.random() * 4,
                       (11 + i / 600 * 6 + random.random() * 0.2) * 1024 ** 3))
rt.cpu, rt.ram, rt.start_time, rt.online, rt.state = 23.0, 17.1 * 1024 ** 3, now - 9000, True, "Online"
rt.players = [("0", "Bob", "x"), ("1", "Alice", "y")]
rt.mods_outdated = ["1"]
app.mgr.sys_mem = (40 * 1024 ** 3, 64 * 1024 ** 3)
app.mgr.is_running = lambda srv: srv is s

def shots():
    app.nb.select(app.perf_tab)
    root.after(800, lambda: (app._refresh_header(), root.after(600, perf)))

def perf():
    c = app.ram_chart
    c.event_generate("<Motion>", x=int(c.winfo_width() * 0.7), y=60)
    root.after(400, lambda: (_shot(["import", "-window", "root", os.path.join(out, "perf.png")]), auto()))

def auto():
    app.nb.select(4)
    root.after(700, lambda: (_shot(["import", "-window", "root", os.path.join(out, "auto.png")]), settings()))

def settings():
    app._settings_dialog()
    root.after(900, lambda: (_shot(["import", "-window", "root", os.path.join(out, "settings.png")]), done()))

def done():
    app.mgr.stop_event.set(); root.destroy()

root.after(1500, shots)
root.mainloop()
print("errors:", errors)
assert not errors
print("GUI OK")
