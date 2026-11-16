"""Live Discord status message: Tamer posts one webhook message (?wait=true to learn its id), then edits that same
message (PATCH .../messages/<id>) only when something changed; a deleted message is posted again; servers can be
hidden; names are optional and escaped; a webhook of its own wins over the alerts one; a forum thread_id is kept;
and closing says Tamer is closed. A pretend Discord on localhost records every request."""
import http.server, json, os, sys, threading, time
sys.path.insert(0, sys.argv[1]); import tamer as am

calls, deleted = [], set()


class Discord(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def answer(self, code, body=None):
        data = json.dumps(body or {}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        calls.append(("POST", self.path, body))
        self.answer(200, {"id": f"msg{len([c for c in calls if c[0] == 'POST'])}"})

    def do_PATCH(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        calls.append(("PATCH", self.path, body))
        msg = self.path.split("/messages/")[1].split("?")[0]
        self.answer(404 if msg in deleted else 200, {"id": msg})


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Discord)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_address[1]}/api/webhooks"

cfg = am.AppConfig(); cfg.data["servers"] = []
cfg.data.update(discord_webhook=f"{base}/1/alerts", status_board=True)
for i, (name, mp) in enumerate((("Island PvE", "TheIsland_WP"), ("Rag*PvP*", "Ragnarok_WP"), ("Secret", "TheIsland_WP")), 1):
    s = am.default_server(i, cfg.servers); s.update(name=name, map=mp, max_players=70)
    cfg.servers.append(s)
cfg.servers[2]["status_board"] = False  # hidden
cfg.save()
mgr = am.Manager(cfg, lambda *a: None)
a, b, hidden = cfg.servers
ra, rb = mgr.runtime(a["id"]), mgr.runtime(b["id"])
ra.state, ra.online, ra.players = "Online", True, [("0", "Rex", "id1"), ("1", "Kib_ble", "id2")]
rb.state = "Stopped"
desc = lambda c: c[2]["embeds"][0]["description"]

assert mgr.status_board_update() == ""
assert [c[:2] for c in calls] == [("POST", "/api/webhooks/1/alerts?wait=true")], calls
d = desc(calls[0])
assert "🟢 **Island PvE**: Online · 2/70 players · The Island" in d, d
assert "🔴 **Rag\\*PvP\\***: Stopped · Ragnarok" in d, d  # Discord formatting in names is escaped
assert "Secret" not in d and "Rex" not in d  # hidden server; names are off
assert "Last checked <t:" in d and calls[0][2]["embeds"][0]["title"] == "Server status"
assert am.AppConfig().data["status_message"]["id"] == "msg1"
# nothing changed: no request
assert mgr.status_board_update() == "" and len(calls) == 1
# a change edits the same message
rb.state, rb.busy, rb.progress = "Updating", "Updating", ("Updating", "Downloading", 45.2, 1, 2)
mgr.status_board_update()
assert calls[-1][:2] == ("PATCH", "/api/webhooks/1/alerts/messages/msg1"), calls[-1][:2]
assert "🔧 **Rag\\*PvP\\***: Updating 45%" in desc(calls[-1])
rb.busy = rb.progress = None
rb.state, rb.online = "Online", True
b["rate_event_state"] = {"names": ["Weekend 2x"], "keys": {}}
mgr.status_board_update()
assert "EVENT: Weekend 2x" in desc(calls[-1]) and calls[-1][2]["embeds"][0]["color"] == am.DISCORD_COLORS["good"]
# names, when switched on (escaped too)
cfg.data["status_board_names"] = True
mgr.status_board_update()
assert "\n   Rex, Kib\\_ble" in desc(calls[-1]), desc(calls[-1])
# every 10 minutes it edits anyway, so "last checked" stays true
n = len(calls); mgr._board_at -= mgr.STATUS_REFRESH + 1
mgr.status_board_update(); assert len(calls) == n + 1 and calls[-1][0] == "PATCH"
# the message was deleted in Discord: post a new one and remember it
deleted.add("msg1"); ra.players = ra.players[:1]
mgr.status_board_update()
assert [c[0] for c in calls[-2:]] == ["PATCH", "POST"] and am.AppConfig().data["status_message"]["id"] == "msg2"
# a webhook of its own (in a forum thread) wins, and starts its own message
cfg.data["status_webhook"] = f"{base}/2/status?thread_id=99"
mgr.status_board_update()
assert calls[-1][:2] == ("POST", "/api/webhooks/2/status?thread_id=99&wait=true"), calls[-1][:2]
ra.players = []
mgr.status_board_update()
assert calls[-1][:2] == ("PATCH", "/api/webhooks/2/status/messages/msg3?thread_id=99"), calls[-1][:2]
# closing
mgr.status_board_update(force=True, closed=True)
assert "⚪ Tamer is closed - status not updating" in desc(calls[-1]) and "Last checked" not in desc(calls[-1])
# switched off: nothing, unless forced (Post now)
cfg.data["status_board"] = False; n = len(calls); rb.state = "Stopped"
assert mgr.status_board_update() == "" and len(calls) == n
# Post now tries a typed webhook without saving it
assert mgr.status_board_update(force=True, url=f"{base}/3/typed") == ""
assert calls[-1][:2] == ("POST", "/api/webhooks/3/typed?wait=true"), calls[-1][:2]
assert "typed" not in am.AppConfig().data.get("status_webhook", "")
# a bad webhook says what went wrong instead of crashing
err = mgr.status_board_update(force=True, url="http://127.0.0.1:1/api/webhooks/x/y")
assert err.startswith("Couldn't reach Discord"), err
# the tick runs it in the background, at most once a minute
cfg.data["status_board"] = True; mgr._board_checked = 0; n = len(calls); rb.state = "Starting"
cfg.data["status_webhook"] = ""; cfg.data["status_message"] = {}
mgr._status_board_tick()
end = time.time() + 10
while len(calls) == n and time.time() < end:
    time.sleep(0.05)
assert len(calls) == n + 1 and "🟡" in desc(calls[-1])
time.sleep(0.2); rb.state = "Stopped"; mgr._status_board_tick(); time.sleep(0.5)
assert len(calls) == n + 1, "checked again within a minute"
mgr.stop_event.set(); srv.shutdown()
print("status board: post, edit only on change, 10-min refresh, deleted -> repost, own webhook + thread, names, "
      "hidden servers, closed, Post now, errors, background tick")
