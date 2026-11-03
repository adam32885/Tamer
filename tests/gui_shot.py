import os as _os, subprocess as _sp, shutil as _sh
_shot = (lambda cmd, **k: _sp.run(cmd, **k)) if _sh.which("import") else (lambda *a, **k: None)  # screenshots need ImageMagick (Linux)
"""Launch the GUI headless, cycle through tabs and screenshot each one."""
import subprocess, sys, os
sys.path.insert(0, sys.argv[1])
import tamer as am
import tkinter as tk

out = sys.argv[2]
root = tk.Tk()
app = am.App(root)
# seed some fake runtime state for the screenshot
s = app.cfg.servers[0]
rt = app.mgr.runtime(s["id"])
app.mgr.log(s, "Settings saved.")
app.mgr.console(s, "> ListPlayers\n0. Bob, 0002abc\n[chat] Bob (Bob): hi")
rt.players = [("0", "Bob", "0002abc")]
errors = []
root.report_callback_exception = lambda *a: errors.append(a)

steps = [(0, None), (1, 0), (1, 1), (2, None), (3, None), (4, None)]
def step(i=0):
    if i > 0:
        _shot(["import", "-window", "root", os.path.join(out, f"tab{i-1}.png")])
    if i >= len(steps):
        app.mgr.stop_event.set()
        root.destroy()
        return
    tab, sub = steps[i]
    app.nb.select(tab)
    if sub is not None:
        app.ini_nb.select(sub)
    if i == 2:  # in GUS tab: common -> ini sync check
        pass
    root.after(900, lambda: step(i + 1))

def go():
    # Exercise the form: change a common setting then switch to the raw INI tab
    app.nb.select(1)
    app.common_vars[(am.GUS, am.SS, "XPMultiplier")].set("3.0")
    app.common_vars[(am.GINI, am.GM, "EggHatchSpeedMultiplier")].set("20")
    root.after(1500, step)
root.after(1500, go)
root.mainloop()
print("errors:", errors)
gus = app.ini_texts[am.GUS].get("1.0", "end-1c")
print("GUS text:", repr(gus))
