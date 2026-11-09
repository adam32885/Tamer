"""Players tab > Admins: the cluster servers share one admin list and other servers keep their own; Tamer writes
ShooterGame\\Saved\\AllowedCheaterAccountIDs.txt for each, keeps IDs already in those files, adds online players
(Make admin) or pasted IDs, removes them, fills in names when admins are seen online, says which running servers
need a restart, and writes the file again before a server starts."""
import os, sys, tempfile
sys.path.insert(0, sys.argv[1]); import tamer as am; import tkinter as tk

ID_OLD, ID_C, ID_REX, ID_NEW = "0002" + "a" * 28, "0002" + "c" * 28, "0002" + "1" * 28, "0002" + "f" * 28
work = tempfile.mkdtemp(prefix="tamer_admins_")
cfg = am.AppConfig(); cfg.data.update(theme="dark", tamer_update_check=False); cfg.data["servers"] = []
for i, (name, cluster) in enumerate((("Alpha", True), ("Bravo", True), ("Charlie", False)), 1):
    s = am.default_server(i, cfg.servers); s.update(name=name, cluster=cluster, install_dir=os.path.join(work, name))
    os.makedirs(os.path.join(s["install_dir"], am.SAVED_REL)); cfg.servers.append(s)
cfg.save()


def admin_path(name):
    return os.path.join(work, name, am.SAVED_REL, am.ADMIN_FILE)


def file_ids(name):
    with open(admin_path(name), encoding="utf-8") as f:
        return f.read().split()


# admins set up by hand before Tamer managed them
with open(admin_path("Alpha"), "w", encoding="utf-8") as f:
    f.write("# my admins\n" + ID_OLD + "\n\n")
with open(admin_path("Charlie"), "w", encoding="utf-8") as f:
    f.write(ID_C + "\n")

am.Manager.ensure_steamcmd = lambda self, srv: (_ for _ in ()).throw(RuntimeError("no SteamCMD in tests"))
infos, errs, asks = [], [], []
am.messagebox.showinfo = lambda t, m, **k: infos.append(m)
am.messagebox.showerror = lambda t, m, **k: errs.append(m)
am.messagebox.askyesno = lambda t, m, **k: asks.append(m) or True
answers = []
am.simpledialog.askstring = lambda t, m, **k: answers.pop(0)
root = tk.Tk(); app = am.App(root); errors = []
root.report_callback_exception = lambda *a: (errors.append(a), __import__("traceback").print_exception(*a), root.destroy())
running = {"Alpha"}
app.mgr.is_running = lambda srv: srv["name"] in running


def pick(name):
    app.tree.selection_set(next(s["id"] for s in app.cfg.servers if s["name"] == name)); root.update()


def shown():
    return [tuple(app.atree.item(i, "values")) for i in app.atree.get_children()]


def srv(name):
    return next(s for s in app.cfg.servers if s["name"] == name)


def a():
    pick("Alpha")
    assert shown() == [("(name unknown)", ID_OLD)], shown()  # kept from the hand-made file
    assert app.admin_scope.cget("text") == "Admins - all 2 cluster servers", app.admin_scope.cget("text")
    # Make admin on an online player
    rt = app.mgr.runtime(srv("Alpha")["id"]); rt.players = [("0", "Rex", ID_REX)]
    app._refresh_header(); root.update()
    app.ptree.selection_set(app.ptree.get_children()[0]); app._admin_add_online(); root.update()
    assert shown() == [("(name unknown)", ID_OLD), ("Rex", ID_REX)], shown()
    assert file_ids("Alpha") == file_ids("Bravo") == [ID_OLD, ID_REX], (file_ids("Alpha"), file_ids("Bravo"))
    assert infos and "next restart of: Alpha." in infos[-1], infos  # only Alpha is running
    assert am.AppConfig().data["cluster_admins"][1] == {"id": ID_REX, "name": "Rex"}
    # adding the same player again does nothing
    infos.clear(); app._admin_add_online(); root.update()
    assert "already an admin" in infos[-1] and len(shown()) == 2, (infos, shown())
    # a bad ID is refused, a good one is added with its name
    answers[:] = ["not-an-id"]; app._admin_add_by_id(); root.update()
    assert errs and "isn't an EOS ID" in errs[-1] and len(shown()) == 2, errs
    answers[:] = ["  " + ID_NEW + " ", "Tamer Tester"]; app._admin_add_by_id(); root.update()
    assert shown()[-1] == ("Tamer Tester", ID_NEW) and file_ids("Bravo") == [ID_OLD, ID_REX, ID_NEW], shown()
    # the old admin is seen online: the name fills in
    rt.players = [("0", "Oldtimer", ID_OLD)]; app._refresh_header(); root.update()
    assert shown()[0] == ("Oldtimer", ID_OLD), shown()
    # remove
    app.atree.selection_set(app.atree.get_children()[1]); app._admin_remove(); root.update()
    assert "Remove Rex" in asks[-1] and [r[1] for r in shown()] == [ID_OLD, ID_NEW], shown()
    assert file_ids("Alpha") == file_ids("Bravo") == [ID_OLD, ID_NEW]
    # Bravo shows the same shared list
    pick("Bravo")
    assert [r[1] for r in shown()] == [ID_OLD, ID_NEW], shown()
    # Charlie isn't in the cluster: its own list, starting from its own file, which the cluster never touched
    pick("Charlie")
    assert shown() == [("(name unknown)", ID_C)], shown()
    assert app.admin_scope.cget("text") == "Admins - this server only"
    assert file_ids("Charlie") == [ID_C]
    infos.clear(); answers[:] = [ID_NEW, ""]; app._admin_add_by_id(); root.update()
    assert file_ids("Charlie") == [ID_C, ID_NEW] and not infos, infos  # Charlie isn't running: no restart note
    assert [a["id"] for a in am.AppConfig().servers[2]["admins"]] == [ID_C, ID_NEW]
    # the file is written again before a start (e.g. deleted, or a fresh install)
    os.remove(admin_path("Bravo"))
    app.mgr.is_installed = lambda s: True
    app.mgr.ports_in_use_by_other = lambda s: None
    started = []
    app.mgr.build_command = lambda s: started.append(file_ids(s["name"])) or (_ for _ in ()).throw(RuntimeError("stop here"))
    try:
        app.mgr._start(srv("Bravo"))
    except RuntimeError:
        pass
    assert started == [[ID_OLD, ID_NEW]], started
    print("admins: shared cluster list, own list, kept old IDs, make admin, add by ID, names, remove, written on start")
    app.mgr.stop_event.set(); root.destroy()


root.after(1500, a); root.mainloop(); print("errors:", errors); assert not errors; print("GUI OK")
