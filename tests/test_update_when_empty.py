"""Update restarts don't make an empty server wait: a game (or mod) update with nobody online restarts straight away,
and if everyone leaves during the warning countdown it restarts then. Scheduled restarts keep their set time, and
cancelling still works."""
import datetime as dt, os, sys, tempfile, threading, time
sys.path.insert(0, sys.argv[1]); import tamer as am

work = tempfile.mkdtemp(prefix="tamer_upd_empty_")
cfg = am.AppConfig(os.path.join(work, "config.json"))
cfg.data["servers"] = [am.default_server(1, [])]
s = cfg.servers[0]
mgr = am.Manager(cfg, lambda *a, **k: None)
mgr.EMPTY_CHECK = 0.1
done = []
mgr.broadcast = mgr.alert = lambda *a, **k: None
mgr._stop = lambda srv, **k: done.append("stop")
mgr._update = lambda srv, **k: done.append("update")
mgr._start = lambda srv: done.append("start")
mgr.is_running = lambda srv: True
rt = mgr.runtime(s["id"])
log = lambda: "\n".join(rt.log)


def run(*args, **kw):
    done.clear(); rt.cancel_event.clear()
    t0 = time.time()
    mgr.op_restart(s, *args, **kw)
    return time.time() - t0


# nobody online: a game update restarts at once, with no 15-minute countdown
rt.online, rt.players_ready, rt.players = True, True, []
took = run(True, [15, 10, 5, 1], None, "Game update", True)
assert took < 2 and done == ["stop", "update", "start"], (took, done)
assert "Game update: nobody is online, so restarting now." in log()

# a player list Tamer hasn't read yet doesn't count as empty
rt.players_ready = False
threading.Timer(0.5, rt.cancel_event.set).start()
took = run(True, [1], None, "Game update", True)
assert done == [] and took < 3, "unknown players must get the countdown (cancelled here)"
rt.players_ready = True

# someone online: warnings start; when they leave, it restarts then instead of after the full countdown
rt.players = [("1", "Adam")]
threading.Timer(0.6, lambda: setattr(rt, "players", [])).start()
took = run(False, [15, 1], None, "Mod update: Arkitect", True)
assert took < 3 and done == ["stop", "start"], (took, done)
assert "Everyone has left - doing the restart now instead of waiting." in log()

# cancelling an update countdown still works
rt.players = [("1", "Adam")]
threading.Timer(0.5, rt.cancel_event.set).start()
took = run(True, [15], None, "Game update", True)
assert done == [] and took < 3 and "Restart cancelled." in log()

# a scheduled restart keeps its time even with nobody online
rt.players = []
target = dt.datetime.now() + dt.timedelta(seconds=2)
took = run(False, [1], target, "Scheduled restart")
assert took >= 1.8 and done == ["stop", "start"], (took, done)

# the background checks ask for this on game and mod update restarts
calls = []
mgr.run_op = lambda srv, label, fn, *a: calls.append((label, a)) or True
mgr._mod_update_restart(s, rt, "Arkitect", True)
assert calls[-1][1][-1] is True, calls
print("update restarts: empty restarts now, everyone leaving ends the countdown, cancel works, "
      "scheduled restarts keep their time")
