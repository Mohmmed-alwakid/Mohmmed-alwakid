"""Kingshot cloud demo: standalone SIMULATION ONLY, no actual game controls."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import RLock, Thread, Event
import os, hmac, json, time, uuid, http.client, ipaddress

state = {"mode":"simulation_only","live_game_connected":False,"resources":700,
    "resource_ready":True,"builder_idle":True,"training_idle":True,
    "running":False,"actions_executed":0,"purchases":"blocked","pvp":"blocked"}
events = []
cooldowns = {"resource": 0.0, "build": 0.0, "training": 0.0}
lock = RLock()
halt = Event()
admin = os.getenv("ADMIN_TOKEN","")
boot_id = uuid.uuid4().hex[:12]
boot_at = time.monotonic()
last_logged_http = {}

def tick():
    with lock:
        if not state["running"]: return
        now = time.monotonic()
        if now >= cooldowns["resource"]: state["resource_ready"] = True
        if now >= cooldowns["build"]: state["builder_idle"] = True
        if now >= cooldowns["training"]: state["training_idle"] = True
        action = ""
        if state["resource_ready"]:
            state["resources"] += 120
            state["resource_ready"] = False
            cooldowns["resource"] = now + 60
            action = "collect_resources"
        elif state["builder_idle"] and state["resources"] >= 300:
            state["resources"] -= 300
            state["builder_idle"] = False
            cooldowns["build"] = now + 90
            action = "upgrade_building"
        elif state["training_idle"] and state["resources"] >= 100:
            state["resources"] -= 100
            state["training_idle"] = False
            cooldowns["training"] = now + 60
            action = "train_troops"
        if action:
            state["actions_executed"] += 1
            events.insert(0, {"action":action,"verified":True,"mock_only":True})
            del events[50:]
            print(f"SIMULATION_ACTION action={action} count={state['actions_executed']}", flush=True)

def worker():
    while not halt.wait(5):
        tick()

def local_smoke(port):
    """Single startup-only loopback test. Never used to keep a free host awake."""
    time.sleep(0.2)
    checks = (("GET", "/healthz", 200), ("GET", "/api/status", 200),
              ("HEAD", "/healthz", 200), ("POST", "/api/control", 401))
    try:
        for method, path, expected in checks:
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
            try:
                connection.request(method, path)
                response = connection.getresponse()
                body = response.read()
                if response.status != expected:
                    raise AssertionError(f"{path}: expected {expected}, got {response.status}")
                if method == "GET":
                    decoded = json.loads(body)
                    if decoded.get("mode") != "simulation_only":
                        raise AssertionError("unexpected response mode")
            finally:
                connection.close()
        print(f"SIM_LOCAL_HTTP_SMOKE result=PASS checks={len(checks)} boot_id={boot_id}", flush=True)
    except Exception as exc:
        print(f"SIM_LOCAL_HTTP_SMOKE result=FAIL error_type={type(exc).__name__} boot_id={boot_id}", flush=True)

class Handler(BaseHTTPRequestHandler):
    def respond(self,code,payload,kind="application/json"):
        if not isinstance(payload,bytes): payload=json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type",kind)
        self.send_header("Content-Length",str(len(payload)))
        self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        self.end_headers()
        if self.command != "HEAD":
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                return
        # Log a bounded sample only; never log query strings or authorization headers.
        route = self.path.split("?", 1)[0]
        if route in ("/healthz", "/api/status"):
            now = time.monotonic()
            with lock:
                # Classify the direct socket peer without logging its IP address.
                # A non-loopback peer demonstrates inbound network traffic to the app,
                # but does NOT by itself prove public internet reachability.
                try:
                    peer_class = "loopback" if ipaddress.ip_address(self.client_address[0]).is_loopback else "nonloopback"
                except ValueError:
                    peer_class = "unknown"
                key = (self.command, route, code, peer_class)
                previous = last_logged_http.get(key, float("-inf"))
                if now - previous >= 60:
                    last_logged_http[key] = now
                    print(f"SIM_HTTP_RESPONSE method={self.command} route={route} status={code} peer_class={peer_class} boot_id={boot_id}", flush=True)
    def do_GET(self):
        path=self.path.split("?",1)[0]
        if path=="/healthz":
            return self.respond(200,{"ok":True,"mode":"simulation_only","boot_id":boot_id,"uptime_seconds":int(time.monotonic()-boot_at)})
        if path=="/api/status":
            with lock: data=dict(state)
            return self.respond(200,data)
        if path=="/api/events":
            with lock: data={"events":list(events)}
            return self.respond(200,data)
        if path=="/":
            page='''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Kingshot AI Cloud Simulator</title><style>body{font:16px system-ui;background:#101727;color:#e6ecf7;max-width:750px;margin:40px auto;padding:22px}pre{background:#1c2944;padding:24px;border-radius:12px;overflow:auto}.c{color:#fbbf7e}</style></head><body><h1>Kingshot AI Cloud Simulator</h1><p class="c">Demo only. No live Kingshot account, Android device or game controls connected.</p><h2>Agent status</h2><pre id="state">Loading...</pre><h2>Actions</h2><pre id="log">Loading...</pre><p>Cloud free tiers may sleep or reset memory; 24/7 service is not guaranteed.</p><script>async function r(){try{let s=await(await fetch('/api/status')).json();let e=await(await fetch('/api/events')).json();document.getElementById('state').textContent=JSON.stringify(s,null,2);document.getElementById('log').textContent=JSON.stringify(e.events,null,2)}catch(x){document.getElementById('state').textContent='Service not available'}}r();setInterval(r,5000)</script></body></html>'''
            return self.respond(200,page.encode(),"text/html; charset=utf-8")
        return self.respond(404,{"error":"not found"})
    def do_HEAD(self):
        path = self.path.split("?", 1)[0]
        if path == "/healthz":
            return self.respond(200,{"ok":True,"mode":"simulation_only","boot_id":boot_id})
        return self.respond(404,{"error":"not found"})
    def do_POST(self):
        if self.path!="/api/control":return self.respond(404,{"error":"not found"})
        if len(admin)<16 or not hmac.compare_digest(self.headers.get("Authorization",""),"Bearer "+admin):
            return self.respond(401,{"error":"operator auth required"})
        try:
            length=int(self.headers.get("Content-Length","0"))
            if length<1 or length>1024:raise ValueError()
            body=json.loads(self.rfile.read(length))
            if not isinstance(body,dict) or body.get("action") not in ("start","stop"):raise ValueError()
        except (ValueError,TypeError):
            return self.respond(400,{"error":"invalid request"})
        with lock:
            state["running"]=body["action"]=="start"
            snapshot={"running":state["running"],"mode":"simulation_only"}
        return self.respond(200,snapshot)
    def log_message(self,*args):pass

if __name__=="__main__":
    # Safe public simulation auto-starts; POST controls require a separately configured secret.
    # Without ADMIN_TOKEN, all operator API calls are rejected; no real-game controls exist.
    state["running"]=True
    port = int(os.getenv("PORT", "10000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"SIM_HTTP_LISTENING host=0.0.0.0 port={port} boot_id={boot_id} mode=simulation_only", flush=True)
    Thread(target=worker,daemon=True).start()
    Thread(target=local_smoke,args=(port,),daemon=True).start()
    server.serve_forever()
