"""Kingshot cloud demo: standalone SIMULATION ONLY, no actual game controls."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import RLock, Thread, Event
import os, hmac, json

state = {"mode":"simulation_only","live_game_connected":False,"resources":700,
    "resource_ready":True,"builder_idle":True,"training_idle":True,
    "running":False,"actions_executed":0,"purchases":"blocked","pvp":"blocked"}
events = []
lock = RLock()
halt = Event()
admin = os.getenv("ADMIN_TOKEN","")

def tick():
    with lock:
        if not state["running"]: return
        action = ""
        if state["resource_ready"]:
            state["resources"] += 120
            state["resource_ready"] = False
            action = "collect_resources"
        elif state["builder_idle"] and state["resources"] >= 300:
            state["resources"] -= 300
            state["builder_idle"] = False
            action = "upgrade_building"
        elif state["training_idle"] and state["resources"] >= 100:
            state["resources"] -= 100
            state["training_idle"] = False
            action = "train_troops"
        if action:
            state["actions_executed"] += 1
            events.insert(0, {"action":action,"verified":True,"mock_only":True})
            del events[50:]

def worker():
    while not halt.wait(5):
        tick()

class Handler(BaseHTTPRequestHandler):
    def respond(self,code,payload,kind="application/json"):
        if not isinstance(payload,bytes): payload=json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type",kind)
        self.send_header("Content-Length",str(len(payload)))
        self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        self.end_headers()
        self.wfile.write(payload)
    def do_GET(self):
        path=self.path.split("?",1)[0]
        if path=="/healthz":
            return self.respond(200,{"ok":True,"mode":"simulation_only"})
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
    auto=os.getenv("AUTO_START","0")=="1"
    if auto and len(admin)<16:raise SystemExit("AUTO_START requires ADMIN_TOKEN (16+ chars)")
    state["running"]=auto
    Thread(target=worker,daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0",int(os.getenv("PORT","8080"))),Handler).serve_forever()
