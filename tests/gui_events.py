"""Schedule tab > Rate events...: make a weekly event in the window (name, days and times, servers, settings),
see when it really switches, catch mistakes (no name, bad time, no server, no setting, not a number), save it,
and delete it. A server start writes the event's values, and the header and Schedule tab say it's on."""
import datetime as dtm, os, sys, tempfile
sys.path.insert(0, sys.argv[1]); import tamer as am; import tkinter as tk

work = tempfile.mkdtemp(prefix="tamer_gui_events_")
cfg = am.AppConfig(); cfg.data.update(theme="dark", tamer_update_check=False); cfg.data["servers"] = []
for i, name in enumerate(("Alpha", "Bravo"), 1):
    s = am.default_server(i, cfg.servers); s.update(name=name, install_dir=os.path.join(work, name),
                                                    restart_times="04:00" if name == "Alpha" else "")
    cfg.servers.append(s)
cfg.save()
am.Manager.ensure_steamcmd = lambda self, srv: (_ for _ in ()).throw(RuntimeError("no SteamCMD in tests"))
infos, errs, asks = [], [], []
am.messagebox.showinfo = lambda t, m, **k: infos.append(m)
am.messagebox.showerror = lambda t, m, **k: errs.append(m)
am.messagebox.askyesno = lambda t, m, **k: asks.append(m) or True
root = tk.Tk(); app = am.App(root); errors = []
root.report_callback_exception = lambda *a: (errors.append(a), __import__("traceback").print_exception(*a), root.destroy())


def srv(name):
    return next(s for s in app.cfg.servers if s["name"] == name)


def a():
    app.tree.selection_set(srv("Alpha")["id"]); root.update()
    app._events_dialog(); root.update()
    d = app._events_win; e = d.ev; v = e["vars"]
    assert e["servers"][srv("Alpha")["id"]].get() and not e["servers"][srv("Bravo")["id"]].get()  # the selected one
    # mistakes are caught
    e["save"](); assert "Give the event a name" in errs[-1]
    v["name"].set("Weekend 2x"); v["start_time"].set("25:00"); root.update()
    assert "Check the times" in e["note"].cget("text")
    e["save"](); assert "Check the times" in errs[-1]
    v["start_time"].set("18:00"); v["start_day"].set("Friday"); v["end_day"].set("Monday"); v["end_time"].set("00:00")
    e["save"](); assert "Add at least one setting" in errs[-1]
    e["pick"].set("Taming speed (TamingSpeedMultiplier)"); e["value"].set("lots"); e["add"]()
    assert "isn't a number" in errs[-1] and e["settings"] == []
    e["value"].set("3"); e["add"]()
    e["pick"].set("Mating interval (MatingIntervalMultiplier)"); e["value"].set("0.5"); e["add"]()
    e["pick"].set("Taming speed (TamingSpeedMultiplier)"); e["value"].set("2"); e["add"]()  # changes, not doubles
    assert [x[2:] for x in e["settings"]] == [["MatingIntervalMultiplier", "0.5"], ["TamingSpeedMultiplier", "2"]]
    e["pick"].set("PvE server (ServerPVE)"); e["value"].set("maybe"); e["add"]()
    assert "True or False" in errs[-1]
    e["pick"].set("PvE server (ServerPVE)"); e["value"].set("true"); e["add"]()
    assert e["settings"][-1][3] == "True"
    e["stree"].selection_set(str(len(e["settings"]) - 1)); d.ev["stree"].event_generate("<<TreeviewSelect>>")
    [b for b in e["stree"].master.winfo_children()[1].winfo_children() if b.cget("text") == "Remove"][0].invoke()
    assert len(e["settings"]) == 2
    e["servers"][srv("Alpha")["id"]].set(False); e["save"](); assert "Tick at least one server" in errs[-1]
    e["servers"][srv("Alpha")["id"]].set(True); e["servers"][srv("Bravo")["id"]].set(True); root.update()
    note = e["note"].cget("text")
    assert "Alpha: " in note and "switches at the restart on Sat" in note and "Bravo: no daily restart times" in note, note
    e["save"](); root.update()
    assert "Saved \"Weekend 2x\"" in infos[-1]
    ev = am.AppConfig().data["rate_events"][0]
    assert ev["name"] == "Weekend 2x" and ev["start_day"] == 4 and ev["end_day"] == 0 and ev["repeat"] == "weekly"
    assert set(ev["servers"]) == {srv("Alpha")["id"], srv("Bravo")["id"]}
    assert e["tree"].item(ev["id"], "values") == ("Fri 18:00 - Mon 00:00 weekly",)
    assert "Rate events for this server: Weekend 2x" in app.events_lbl.cget("text")
    # editing keeps one event
    v["name"].set("Weekend 3x"); e["save"]()
    assert [x["name"] for x in app.cfg.data["rate_events"]] == ["Weekend 3x"]
    # a start while it's on writes the values; the header and Schedule tab say so
    app.cfg.data["rate_events"][0].update(start_day=0, start_time="00:00", end_day=0, end_time="00:00")  # always on
    s = srv("Alpha")
    app.mgr.is_installed = lambda x: True
    app.mgr.ports_in_use_by_other = lambda x: None
    app.mgr.build_command = lambda x: (_ for _ in ()).throw(RuntimeError("stop here"))
    try:
        app.mgr._start(s)
    except RuntimeError:
        pass
    text = am.read_text_file(os.path.join(app.mgr.config_dir(s), "GameUserSettings.ini"))
    assert am.ini_get(text, "ServerSettings", "TamingSpeedMultiplier") == "2", text
    root.update(); app._refresh_header(); root.update()
    assert "EVENT: Weekend 3x" in app.h_info.cget("text"), app.h_info.cget("text")
    assert "Weekend 3x (on now)" in app.events_lbl.cget("text")
    assert any("Rate event on: Weekend 3x" in ln for ln in app.mgr.runtime(s["id"]).log), list(app.mgr.runtime(s["id"]).log)[-5:]
    # delete
    e["tree"].selection_set(ev["id"]); root.update(); e["delete"](); root.update()
    assert "Delete \"Weekend 3x\"?" in asks[-1] and am.AppConfig().data["rate_events"] == []
    assert app.events_lbl.cget("text") == ""
    print("rate events window: validation, switch notes, save/edit/delete, applied at start, header + label")
    app.mgr.stop_event.set(); root.destroy()


root.after(1500, a); root.mainloop(); print("errors:", errors); assert not errors; print("GUI OK")
