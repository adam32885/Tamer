"""Tamer Chat: the bot's settings files, the TamerChat plugin install, and running / restarting / adopting the bot.
Uses a pretend tamer_chat.py, so nothing talks to Discord."""
import json, os, sys, tempfile, time

tmp = tempfile.mkdtemp()
sys.path.insert(0, sys.argv[1])
import tamer as am

am.CHAT_PACKAGES = {"json": "json"}  # the pretend bot needs nothing; real installs check discord.py etc.
bot = os.path.join(tmp, "Tamer_Chat")
os.makedirs(bot)
open(os.path.join(bot, "tamer_chat.py"), "w").write(
    "import os, sys, time\n"
    "print('pretend bot up', os.getpid(), flush=True)\n"
    "while not os.path.exists('crash_now'):\n"
    "    time.sleep(0.2)\n"
    "os.remove('crash_now'); print('pretend bot crashing', flush=True); sys.exit(2)\n")
open(os.path.join(bot, ".env.example"), "w").write("# Copy this to .env\nDISCORD_TOKEN=\nBRIDGE_CHANNEL_ID=\n"
                                                   "# keep me\nBRIDGE_KEY=change-me\nPOLL_SECONDS=2\n")

cfg = am.AppConfig(os.path.join(tmp, "c.json"))
cfg.data.update(chat_dir=bot, update_check_min=0, mod_check_min=0)
s = cfg.servers[0]
s.update(name="Island", install_dir=os.path.join(tmp, "srv"), rcon_port=27020, admin_password="pw1")
s2 = am.default_server(2, cfg.servers); s2.update(name="Scorched", install_dir=os.path.join(tmp, "srv2"))
cfg.servers.append(s2); cfg.save()
m = am.Manager(cfg, lambda *a: None)


def wait(cond, timeout, what):
    end = time.time() + timeout
    while time.time() < end:
        if cond(): return
        time.sleep(0.25)
    print(open(am.chat_log_path(), encoding="utf-8").read() if os.path.exists(am.chat_log_path()) else "(no log)")
    m.chat_stop(); raise SystemExit(f"TIMEOUT waiting for {what}")


def log():
    return open(am.chat_log_path(), encoding="utf-8").read() if os.path.exists(am.chat_log_path()) else ""


# ---------- what's missing, in plain words ----------
assert "No Discord bot token" in m.chat_problem(), m.chat_problem()
am.env_write(os.path.join(bot, ".env"), {"DISCORD_TOKEN": "tok"})
assert "chat channel ID" in m.chat_problem(), m.chat_problem()
am.env_write(os.path.join(bot, ".env"), {"BRIDGE_CHANNEL_ID": "123"})
assert m.chat_problem() == "", m.chat_problem()
print("problems explained")

# ---------- servers.json and .env ----------
assert am.chat_sync(cfg) and not am.chat_sync(cfg), "writes once, then nothing to change"
servers = json.load(open(os.path.join(bot, "servers.json")))
assert [(x["name"], x["port"], x["password"], x["mode"]) for x in servers] == [
    ("Island", 27020, "pw1", "rcon"), ("Scorched", s2["rcon_port"], s2["admin_password"], "rcon")], servers
env_text = open(os.path.join(bot, ".env")).read()
env = am.env_read(os.path.join(bot, ".env"))
assert env["BRIDGE_KEY"] == cfg.data["chat_key"] and len(cfg.data["chat_key"]) == 32, "shared key made and used"
assert env["DISCORD_TOKEN"] == "tok" and env["POLL_SECONDS"] == "2" and "# keep me" in env_text, "other lines kept"
assert env_text.count("BRIDGE_KEY=") == 1, "key replaced, not added twice"
print("servers.json and .env written")

# ---------- the TamerChat plugin ----------
try:
    am.install_chat_plugin(cfg, s); raise AssertionError("must refuse without a built plugin")
except RuntimeError as e:
    assert "hasn't been built" in str(e)
out = os.path.join(bot, "plugin", "out", "TamerChat"); os.makedirs(out)
open(os.path.join(out, "TamerChat.dll"), "w").write("x")
json.dump({"FullName": "Tamer Chat"}, open(os.path.join(out, "PluginInfo.json"), "w"))
json.dump({"ServerName": "Island", "BridgeKey": "change-me", "DiscordInvite": ""}, open(os.path.join(out, "config.json"), "w"))
am.install_chat_plugin(cfg, s)
pconf = os.path.join(am.asaapi_paths(s)["plugins"], "TamerChat", "config.json")
c = json.load(open(pconf))
assert c["ServerName"] == "Island" and c["BridgeKey"] == cfg.data["chat_key"] and c["BridgeUrl"].endswith(":8765/ark/event"), c
assert json.load(open(os.path.join(bot, "servers.json")))[0]["mode"] == "rcon", "AsaApi off: plugin won't load"
s["asaapi"] = True
assert am.chat_sync(cfg) and json.load(open(os.path.join(bot, "servers.json")))[0]["mode"] == "plugin"
c["DiscordInvite"] = "https://discord.gg/mine"; json.dump(c, open(pconf, "w"))
am.install_chat_plugin(cfg, s)
assert json.load(open(pconf))["DiscordInvite"] == "https://discord.gg/mine", "reinstall keeps the server's settings"
print("plugin installed, named and keyed")

# ---------- running the bot ----------
cfg.data["chat_run"] = True
m.start_monitor()
wait(lambda: m.chat_running() and "pretend bot up" in log(), 30, "bot started")
first = m.chat_pid
print("bot started by the monitor")

open(os.path.join(bot, "crash_now"), "w").close()
wait(lambda: m.chat_running() and m.chat_pid != first, 30, "restart after a stop")
assert "stopped (exit code 2)" in log(), log()
print("restarted after it stopped")

second = m.chat_pid
s2["name"] = "Scorched Earth"; m.chat_last_sync = 0  # don't wait the 30 s between checks
wait(lambda: m.chat_running() and m.chat_pid != second, 30, "restart for the new server list")
assert json.load(open(os.path.join(bot, "servers.json")))[1]["name"] == "Scorched Earth"
assert "server list changed" in log()
print("restarted for a renamed server")

m.stop_event.set(); time.sleep(6)                       # Tamer closes: the bot keeps running
assert am.pid_alive(m.chat_pid), "bot survives Tamer closing"
m2 = am.Manager(cfg, lambda *a: None); m2.chat_adopt()
assert m2.chat_pid == m.chat_pid and m2.chat_running(), "the next Tamer picks it up"
print("left running and adopted")

m2.chat_crashes.extend([time.time()] * 4)                # 4 recent stops; one more and it gives up
open(os.path.join(bot, "crash_now"), "w").close()
wait(lambda: not am.pid_alive(m2.chat_pid), 15, "pretend crash")
m2._chat_tick(time.time())
assert not cfg.data["chat_run"] and not m2.chat_running() and "5 times in 10 minutes" in m2.chat_error, m2.chat_error
print("gives up after 5 stops in 10 minutes")

cfg.data["chat_run"] = True; m2.chat_crashes.clear(); m2._chat_tick(time.time())
assert m2.chat_running()
cfg.data["chat_run"] = False; m2._chat_tick(time.time())
assert not m2.chat_running() and not os.path.exists(m2.CHAT_PID_PATH), "switched off: stopped"
print("switching it off stops it")
print("ALL OK")
