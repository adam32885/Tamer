"""Rate events: when a weekly or one-off event is on, the event values written at a start, the normal values put
back afterwards (even after ARK rewrote 3 as 3.000000), a value changed by hand during the event kept as the new
normal, events that are off or for other servers ignored, and the note saying which restart switches them."""
import datetime as dtm, os, sys, tempfile
sys.path.insert(0, sys.argv[1]); import tamer as am

D = lambda *a: dtm.datetime(*a)
fri = D(2026, 11, 6, 0, 0)
assert fri.weekday() == 4
weekend = {"id": "e1", "name": "Weekend 2x", "enabled": True, "repeat": "weekly",
           "start_day": 4, "start_time": "18:00", "end_day": 0, "end_time": "00:00", "servers": ["s1"],
           "settings": [["GameUserSettings.ini", "ServerSettings", "TamingSpeedMultiplier", "3"],
                        ["Game.ini", am.GM, "MatingIntervalMultiplier", "0.5"]]}
# the window: Fri 18:00 -> Mon 00:00, every week
assert am.event_window(weekend, D(2026, 11, 7, 12)) == (D(2026, 11, 6, 18), D(2026, 11, 9, 0))
assert am.event_window(weekend, D(2026, 11, 4, 12)) == (D(2026, 11, 6, 18), D(2026, 11, 9, 0))  # next one
assert am.event_window(weekend, D(2026, 11, 9, 0)) == (D(2026, 11, 13, 18), D(2026, 11, 16, 0))  # just ended
assert am.event_on(weekend, D(2026, 11, 6, 18)) and not am.event_on(weekend, D(2026, 11, 6, 17, 59))
assert am.event_on(weekend, D(2026, 11, 8, 23, 59)) and not am.event_on(weekend, D(2026, 11, 9, 0))
assert not am.event_on(dict(weekend, enabled=False), D(2026, 11, 7, 12))
same_day = dict(weekend, start_day=2, start_time="20:00", end_day=2, end_time="22:00")  # Wed 20-22
assert am.event_on(same_day, D(2026, 11, 4, 21)) and not am.event_on(same_day, D(2026, 11, 4, 23))
full_week = dict(weekend, start_day=0, start_time="00:00", end_day=0, end_time="00:00")
assert am.event_on(full_week, D(2026, 11, 4, 3))
once = dict(weekend, repeat="once", start="2026-12-24 18:00", end="2026-12-27 00:00")
assert am.event_on(once, D(2026, 12, 25, 9)) and not am.event_on(once, D(2026, 12, 27, 0))
assert am.event_window(once, D(2027, 1, 1)) is None
assert am.event_when(weekend) == "Fri 18:00 - Mon 00:00 weekly" and am.event_when(once).startswith("2026-12-24")
for bad in (dict(weekend, start_time="25:00"), dict(once, end="2026-12-20 00:00"), dict(once, start="tomorrow")):
    try:
        am.event_window(bad, D(2026, 11, 4))
        raise AssertionError(f"accepted {bad}")
    except ValueError:
        pass
    assert not am.event_on(bad, D(2026, 11, 4))

# applying it
work = tempfile.mkdtemp(prefix="tamer_events_")
cdir = os.path.join(work, "Config")
os.makedirs(cdir)
gus, gini = os.path.join(cdir, "GameUserSettings.ini"), os.path.join(cdir, "Game.ini")
with open(gus, "w") as f:
    f.write("[ServerSettings]\nTamingSpeedMultiplier=1.5\nXPMultiplier=2\n")
cfg = am.AppConfig(); cfg.data["rate_events"] = [weekend]
s = {"id": "s1", "name": "Alpha", "restart_times": "04:00"}
other = {"id": "s2", "name": "Bravo", "restart_times": ""}
rd = lambda p, sec, k: am.ini_get(am.read_text_file(p), sec, k)

msgs = am.apply_rate_events(cfg, s, cdir, D(2026, 11, 4, 4))  # Wednesday: not on, nothing to do
assert msgs == [] and rd(gus, "ServerSettings", "TamingSpeedMultiplier") == "1.5"
msgs = am.apply_rate_events(cfg, s, cdir, D(2026, 11, 7, 4))  # Saturday 04:00 restart: on
assert msgs and msgs[0].startswith("Rate event on: Weekend 2x"), msgs
assert rd(gus, "ServerSettings", "TamingSpeedMultiplier") == "3" and rd(gini, am.GM, "MatingIntervalMultiplier") == "0.5"
assert rd(gus, "ServerSettings", "XPMultiplier") == "2"  # untouched
assert s["rate_event_state"]["names"] == ["Weekend 2x"]
# ARK rewrites the file on shutdown; a second start during the event keeps the remembered normal values
with open(gus, "w") as f:
    f.write("[ServerSettings]\nTamingSpeedMultiplier=3.000000\nXPMultiplier=2.000000\n")
am.apply_rate_events(cfg, s, cdir, D(2026, 11, 8, 4))
assert s["rate_event_state"]["keys"]["GameUserSettings.ini|ServerSettings|TamingSpeedMultiplier"]["normal"] == "1.5"
msgs = am.apply_rate_events(cfg, s, cdir, D(2026, 11, 9, 4))  # Monday 04:00: over
assert msgs and msgs[0].startswith("Rate event over (Weekend 2x)"), msgs
assert rd(gus, "ServerSettings", "TamingSpeedMultiplier") == "1.5"
assert rd(gini, am.GM, "MatingIntervalMultiplier") is None  # wasn't set before: removed again
assert s["rate_event_state"] == {"names": [], "keys": {}}
# changed by hand during the event: that's the new normal, not undone
am.apply_rate_events(cfg, s, cdir, D(2026, 11, 14, 4))
with open(gus, "w") as f:
    f.write("[ServerSettings]\nTamingSpeedMultiplier=5\n")
am.apply_rate_events(cfg, s, cdir, D(2026, 11, 16, 4))
assert rd(gus, "ServerSettings", "TamingSpeedMultiplier") == "5"
# deleting a running event puts the normal values back at the next start
am.apply_rate_events(cfg, s, cdir, D(2026, 11, 21, 4))
assert rd(gus, "ServerSettings", "TamingSpeedMultiplier") == "3"
cfg.data["rate_events"] = []
am.apply_rate_events(cfg, s, cdir, D(2026, 11, 21, 5))
assert rd(gus, "ServerSettings", "TamingSpeedMultiplier") == "5"
# a server the event isn't for is never touched
cfg.data["rate_events"] = [weekend]
assert am.apply_rate_events(cfg, other, os.path.join(work, "none"), D(2026, 11, 7, 4)) == []
assert not os.path.exists(os.path.join(work, "none"))
# two events setting the same thing: the later one wins
cfg.data["rate_events"] = [weekend, dict(weekend, id="e2", name="Boost", settings=[
    ["GameUserSettings.ini", "ServerSettings", "TamingSpeedMultiplier", "10"]])]
am.apply_rate_events(cfg, s, cdir, D(2026, 11, 7, 4))
assert rd(gus, "ServerSettings", "TamingSpeedMultiplier") == "10" and s["rate_event_state"]["names"] == ["Weekend 2x", "Boost"]
cfg.data["rate_events"] = []
am.apply_rate_events(cfg, s, cdir, D(2026, 11, 10, 4))
assert rd(gus, "ServerSettings", "TamingSpeedMultiplier") == "5"

# when it really switches
s2 = {"id": "s1", "name": "Alpha", "restart_times": "04:00"}
note = am.event_switch_note(s2, weekend, D(2026, 11, 4, 12))
assert note == "Alpha: switches at the restart on Sat 07 Nov 04:00, back to normal on Mon 09 Nov 04:00.", note
assert "only change when you restart it yourself" in am.event_switch_note(other, weekend, D(2026, 11, 4, 12))
assert "won't take effect" in am.event_switch_note(s2, same_day, D(2026, 11, 4, 12))
s2["rate_event_state"] = {"names": ["Weekend 2x"], "keys": {}}
assert am.event_switch_note(s2, weekend, D(2026, 11, 7, 12)) == "Alpha: on now - back to normal at the restart on Mon 09 Nov 04:00."
assert am.event_switch_note(s2, once, D(2027, 1, 1)) == "This one-off event is over."
# Sunday night, no restart left in this weekend's event: talk about next weekend's
s2["rate_event_state"] = {"names": [], "keys": {}}
assert am.event_switch_note(s2, weekend, D(2026, 11, 8, 22)) == \
    "Alpha: switches at the restart on Sat 14 Nov 04:00, back to normal on Mon 16 Nov 04:00."
print("rate events: weekly/once windows, applied and restored at starts, ARK's rewrite, hand edits kept, notes")
