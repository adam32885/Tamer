"""Crash alerts in Discord carry details: the troubleshooter's likely cause, ARK's own crash report
(Saved\\Crashes\\...\\CrashContext.runtime-xml) and the last lines of ShooterGame.log - with passwords, keys,
webhooks and player IDs removed, old files ignored, and the text kept under Discord's limit."""
import os, sys, tempfile, time
sys.path.insert(0, sys.argv[1]); import tamer as am

work = tempfile.mkdtemp(prefix="tamer_crash_")
cfg = am.AppConfig(); cfg.data["servers"] = []
cfg.data["discord_webhook"] = "https://discord.com/api/webhooks/123/abcSECRET"
s = am.default_server(1, cfg.servers); s.update(name="Alpha", install_dir=os.path.join(work, "Alpha"),
                                                admin_password="hunter2pass")
cfg.servers.append(s)
mgr = am.Manager(cfg, lambda *a: None)


def put(rel, text):
    p = os.path.join(s["install_dir"], rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return p


put(am.SERVER_EXE_REL, "")
started = time.time() - 60
log = "\n".join([f"[2026.11.08-20.00.{i:02d}] LogInit: line {i}" for i in range(30)] + [
    "[2026.11.08-20.01.00] Player 0002" + "ab" * 14 + " joined",
    "[2026.11.08-20.01.01] ServerAdminPassword=hunter2pass?Port=7777",
    "[2026.11.08-20.01.02] Fatal error: EXCEPTION_ACCESS_VIOLATION reading address 0x0000",
    "[2026.11.08-20.01.03] with `backticks` in it"])
put(am.GAMELOG_REL, log)
put(os.path.join(am.CRASHES_REL, "UECC-Windows-NEW", "CrashContext.runtime-xml"),
    "<FGenericCrashContext><RuntimeProperties><ErrorMessage>Unhandled Exception: EXCEPTION_ACCESS_VIOLATION "
    "reading address 0x0000000000000010&#10;MyMod_Something.dll</ErrorMessage></RuntimeProperties></FGenericCrashContext>")
old = put(os.path.join(am.CRASHES_REL, "UECC-Windows-OLD", "CrashContext.runtime-xml"),
          "<ErrorMessage>OLD CRASH should not show</ErrorMessage>")
os.utime(os.path.dirname(old), (started - 3600, started - 3600))

text = am.crash_details(mgr, s, since=started)
print(text)
assert "**Likely cause:**" in text and "The server crashed" in text, text
assert "**ARK's crash report:**" in text and "MyMod_Something.dll" in text and "OLD CRASH" not in text
assert "**Last lines of ShooterGame.log:**" in text and "line 29" in text and "line 20" not in text  # last 8 only
assert "hunter2pass" not in text and "(removed)" in text, "admin password must be removed"
assert "ab" * 14 not in text and "(player ID)" in text, "player IDs must be removed"
assert "`backticks`" not in text and text.count("```") % 2 == 0
# a log from before this start doesn't count
os.utime(os.path.join(s["install_dir"], am.GAMELOG_REL), (started - 3600, started - 3600))
assert "Last lines" not in am.crash_details(mgr, s, since=started)
os.utime(os.path.join(s["install_dir"], am.GAMELOG_REL), None)
# long text is cut, keeping code blocks closed
short = am.crash_details(mgr, s, since=started, limit=300)
assert len(short) <= 300 and short.count("```") % 2 == 0, short

# the alert itself: first line, then the details
sent = []
mgr.alert = lambda srv, event, title, desc="", color="info": sent.append((event, title, desc, color))
mgr.CRASH_REPORT_WAIT = 0
mgr._crash_alert(s, "Crashed - restarting", "Exit code 3. Restarting automatically.", started)
end = time.time() + 10
while not sent and time.time() < end:
    time.sleep(0.05)
assert sent, "no alert sent"
event, title, desc, color = sent[0]
assert event == "crash" and title == "Crashed - restarting" and color == "bad"
assert desc.startswith("Exit code 3. Restarting automatically.\n\n**Likely cause:**"), desc
# when the details can't be read, the alert still goes out
sent.clear(); am.crash_details = lambda *a, **k: 1 / 0
mgr._crash_alert(s, "Crashed", "Exit code 1.", started)
end = time.time() + 10
while not sent and time.time() < end:
    time.sleep(0.05)
assert sent and sent[0][2] == "Exit code 1.", sent
mgr.stop_event.set()
print("crash details: cause, crash report, log tail, redacted, old files skipped, cut to fit, alert sent")
