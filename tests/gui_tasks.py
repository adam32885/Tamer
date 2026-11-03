import os as _os, subprocess as _sp, shutil as _sh
_shot = (lambda cmd, **k: _sp.run(cmd, **k)) if _sh.which("import") else (lambda *a, **k: None)  # screenshots need ImageMagick (Linux)
import os, subprocess, sys
sys.path.insert(0, sys.argv[1])
import tamer as am
import tkinter as tk
out = sys.argv[2]
root = tk.Tk()
app = am.App(root)
errors = []
root.report_callback_exception = lambda *a: errors.append(a)
shot = lambda n: _shot(["import", "-window", "root", os.path.join(out, n)])
def go():
    app.nb.select(app.tasks_tab)
    s = app.current()
    s["timed_tasks"] = am.example_tasks()
    s["timed_tasks"][0]["enabled"] = True
    app.mgr.runtime(s["id"]).task_ran[s["timed_tasks"][0]["id"]] = __import__("time").time()
    app._refresh_tasks()
    root.after(600, lambda: (shot("tasks.png"), dialog()))
def dialog():
    app.task_tree.selection_set(app.current()["timed_tasks"][2]["id"])
    root.after(300, lambda: (root.after(900, lambda: (shot("taskdlg.png"), close_top())), app._task_edit()))
def close_top():
    for w in root.winfo_children():
        if isinstance(w, tk.Toplevel): w.destroy()
    root.after(300, settings)
def settings():
    root.after(900, lambda: (shot("set_general.png"), tab(2)))
    app._settings_dialog()
def tab(i):
    top = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)][0]
    nb = [c for c in top.winfo_children()[0].winfo_children() if c.winfo_class() == "TNotebook"][0]
    nb.select(i)
    root.after(1500, lambda: (shot("set_service.png"), end()))
def end():
    app.mgr.stop_event.set(); root.destroy()
root.after(1500, go)
root.mainloop()
print("errors:", errors); assert not errors; print("GUI OK")
