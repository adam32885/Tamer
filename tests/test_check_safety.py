"""Real case (1.24.0): the Schedule tab saved "Longest wait for an empty server" as text ("120"). When a mod update
came out on a server waiting for an empty server, comparing the wait with "120" failed every 5 seconds, and that
stopped Tamer's whole regular check: no backups, scheduled restarts, crash watch or Discord status message for any
server for 20 hours. Now the setting is a number (and saved text is repaired on open), the wait check copes with
a bad value, one server's error is logged and never stops the others, the status message has its own safety net,
and status message errors show on the Log tab."""
import json, os, sys, tempfile, threading, time
sys.path.insert(0, sys.argv[1]); import tamer as am

# numbers saved as text
assert am.as_int("120") == 120 and am.as_int(" 15 ") == 15 and am.as_int("2.0") == 2 and am.as_int(30) == 30
assert am.as_int("lots", 120) == 120 and am.as_int(None, 7) == 7 and am.as_int("", 0) == 0
assert "mod_restart_wait_minutes" in am.INT_KEYS, "the Schedule tab must save it as a number"

work = tempfile.mkdtemp(prefix="tamer_safety_")
path = os.path.join(work, "config.json")
a = am.default_server(1, []); a.update(name="Island", install_dir=os.path.join(work, "a"), mod_restart_wait_minutes="120",
                                       backup_keep="48", port="7779")
b = am.default_server(2, [a]); b.update(name="Valguero", install_dir=os.path.join(work, "b"))
with open(path, "w", encoding="utf-8") as f:
    json.dump({"servers": [a, b]}, f)
cfg = am.AppConfig(path)
sa, sb = cfg.servers
assert sa["mod_restart_wait_minutes"] == 120 and sa["backup_keep"] == 48 and sa["port"] == 7779, sa

mgr = am.Manager(cfg, lambda *a, **k: None)
log = lambda s: "\n".join(mgr.runtime(s["id"]).log)

# the wait check copes with text that sneaks in anyway (this raised TypeError before)
sa["mod_restart_wait_minutes"] = "120"
rt = mgr.runtime(sa["id"])
sa.update(auto_mod_update_restart=True, mod_restart_wait_empty=True)
rt.mod_wait_since, rt.online, rt.players = time.time() - 60, True, [("1", "Someone")]
assert mgr._mod_wait_check(sa, rt) is False  # someone online, 1 of 120 minutes: keep waiting, no error
rt.mod_wait_since = time.time() - 121 * 60
restarts = []
mgr._mod_update_restart = lambda s, r, names, warn: restarts.append((s["name"], warn)) or True
rt.mod_wait_names = "Arkitect Structures Remastered"
assert mgr._mod_wait_check(sa, rt) is True and restarts == [("Island", True)]  # waited too long: restart with warnings

# one server's error is logged once and the others still get their checks (here: their backups)
mgr.is_running = lambda s: True
mgr._sample_resources = mgr._log_window = lambda *a: None
backups = []
mgr.run_op = lambda s, label, *a: backups.append(s["name"]) or True
for s in (sa, sb):
    r = mgr.runtime(s["id"])
    r.polling, r.online, r.busy, r.last_backup = True, True, None, 0
    s.update(backup_interval_min=60, restart_times="")
mgr.first_tick = False; mgr.last_scan = time.time()
mgr.last_mod_check = mgr.last_update_check = time.time()
real_wait = am.Manager._mod_wait_check


def broken(self, s, r):
    if s is sa:
        raise TypeError("'>=' not supported between instances of 'float' and 'str'")
    return real_wait(self, s, r)


mgr._mod_wait_check = broken.__get__(mgr)
rt.mod_wait_since = time.time()
mgr._tick(); mgr._tick(); mgr._tick()
assert "Valguero" in backups, "the other server's backup must still run"
assert log(sa).count("Tamer hit an error checking this server") == 1, log(sa)  # once, not every 5 seconds
assert "TypeError" in log(sa) and "Send a bug report" in log(sa)
mgr._mod_wait_check = real_wait.__get__(mgr)
rt.mod_wait_since = None
mgr._tick()
assert "regular checks for this server are working again" in log(sa), log(sa)[-300:]

# the status message still updates when the regular check fails
cfg.data.update(status_board=True, discord_webhook="http://127.0.0.1:9/none")
ticks = []
mgr._tick = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
mgr._status_board_tick = lambda: ticks.append(1)
mgr.paused = False
t = threading.Thread(target=mgr._monitor, daemon=True); t.start()
time.sleep(1.5); mgr.stop_event.set(); t.join(10)
assert ticks, "the status message must get its turn even when the regular check fails"
assert "RuntimeError: boom" in log(sa)

# status message errors show on the Log tab, once, and so does the recovery
del mgr._status_board_tick
answers = iter(["Discord returned HTTP 404 - check the webhook URL"] * 3 + [""])
mgr.status_board_update = lambda: next(answers)
for _ in range(4):
    mgr._board_checked = 0
    mgr._status_board_tick()
    for _ in range(100):
        if not mgr._board_busy:
            break
        time.sleep(0.02)
    time.sleep(0.05)
assert log(sa).count("Discord status message couldn't be updated: Discord returned HTTP 404") == 1, log(sa)[-600:]
assert "Discord status message is updating again." in log(sa)
print("check safety: text numbers repaired, wait check copes, one server's error doesn't stop the others "
      "(logged once, recovery logged), status message has its own safety net and logs its errors")
