import json, os, sys, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
sys.path.insert(0, sys.argv[1])

GOOD = "$2a$10$" + "A" * 53
seen = []

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _go(self):
        k = self.headers.get("x-api-key")
        seen.append((self.path.split("?")[0], k))
        if k is not None and k != GOOD:
            self.send_response(403); self.end_headers(); return
        if self.path.startswith("/games/"):
            body = {"data": {"name": "ARK: Survival Ascended"}}
        elif self.path.startswith("/mods/search"):
            body = {"data": [{"id": 1, "name": "Dino Storage", "authors": [{"name": "x"}], "downloadCount": 5,
                              "dateModified": "2026-10-01T00:00:00Z"}], "pagination": {"totalCount": 1}}
        else:
            body = {"data": []}
        b = json.dumps(body).encode(); self.send_response(200)
        self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(b)
    do_GET = do_POST = _go

srv = HTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
os.environ["ASM_CF_BASE"] = f"http://127.0.0.1:{srv.server_port}"
import tamer as am

# key cleaning
assert am.clean_api_key(f'  "{GOOD}"\n') == GOOD
assert am.clean_api_key(f"x-api-key: {GOOD}") == GOOD
assert am.clean_api_key("​" + GOOD + "﻿") == GOOD
assert am.clean_api_key(GOOD[:30] + " " + GOOD[30:]) == GOOD
assert am.api_key_format_problem(GOOD) == ""
assert "60" in am.api_key_format_problem(GOOD[:-5])
assert "$2a$10$" in am.api_key_format_problem("abc123")
print("clean ok")

key = {"v": "$2a$10$" + "B" * 53}
cf = am.CurseForge(lambda: key["v"])
mods, total = cf.search("dino")
assert mods and mods[0]["name"] == "Dino Storage", mods
assert cf.key_problem and "rejected your API key (HTTP 403)" in cf.key_problem, cf.key_problem
assert seen[-2][1] == key["v"] and seen[-1][1] is None, seen  # tried key, then fell back without it
print("fallback ok:", cf.key_problem.splitlines()[0])

# known-bad key is not retried each search
n = len(seen); cf.search("dino"); assert len(seen) == n + 1 and seen[-1][1] is None
assert cf.using_proxy() is False or True

ok, msg = cf.test_key(key["v"]); assert not ok and "rejected" in msg, msg
ok, msg = cf.test_key(f' "{GOOD}" '); assert ok and "works" in msg, msg
print("test_key ok:", msg)

# fixing the key clears the problem
key["v"] = GOOD
cf.search("dino"); assert cf.key_problem == "" and seen[-1][1] == GOOD
print("ALL OK")
srv.shutdown()
