#!/usr/bin/env python3
"""
vnpy WebSocket Bridge v2
- Subscribes to vnpy RPC PUB socket (4102) via ZeroMQ SUB
- Parses pickled messages
- Broadcasts JSON to all connected WebSocket clients via asyncio
"""
import asyncio
import pickle
import threading
import json
from datetime import datetime
from websockets.sync.server import serve

PUB_ADDRESS = "tcp://127.0.0.1:4102"
WS_PORT = 8767

clients = set()
clients_lock = threading.Lock()

def decode_msg(raw):
    try:
        obj = pickle.loads(raw)
        if isinstance(obj, list) and len(obj) >= 2:
            return obj[0], obj[1]
        return None, obj
    except Exception as e:
        return None, str(e)

def broadcast(msg_type, data):
    payload = json.dumps({
        "type": msg_type,
        "data": str(data)[:500] if data else None,
        "timestamp": datetime.now().isoformat()
    })
    with clients_lock:
        dead = set()
        for c in clients:
            try:
                c.send(payload)
            except Exception:
                dead.add(c)
        for d in dead:
            clients.discard(d)

def zmq_subscriber():
    import zmq
    ctx = zmq.Context()
    sub = ctx.socket(zmq.SUB)
    sub.connect(PUB_ADDRESS)
    sub.subscribe(b'')
    poller = zmq.Poller()
    poller.register(sub, zmq.POLLIN)

    print(f"[ZMQ] Subscribed to {PUB_ADDRESS}")
    while True:
        events = dict(poller.poll(timeout=2000))
        if sub in events:
            try:
                raw = sub.recv()
                msg_type, data = decode_msg(raw)
                if msg_type:
                    broadcast(msg_type, data)
                    print(f"[ZMQ] Got: {msg_type}")
            except Exception as e:
                print(f"[ZMQ] Error: {e}")

def handler(ws):
    addr = ws.remote_address
    print(f"[WS] Client connected: {addr}")
    with clients_lock:
        clients.add(ws)
    try:
        ws.send(json.dumps({
            "type": "connected",
            "server": "vnpy.mingmingliu.cn",
            "timestamp": datetime.now().isoformat()
        }))
        # Keep connection alive
        while True:
            try:
                msg = ws.recv(timeout=30)
                if msg == "ping":
                    ws.send("pong")
            except Exception:
                pass
    except Exception as e:
        print(f"[WS] Client {addr} disconnected: {e}")
    finally:
        with clients_lock:
            clients.discard(ws)

if __name__ == "__main__":
    # Start ZeroMQ subscriber in daemon thread
    t = threading.Thread(target=zmq_subscriber, daemon=True)
    t.start()
    print(f"[WS] Bridge starting on port {WS_PORT}")
    with serve(handler, "0.0.0.0", WS_PORT) as server:
        server.serve_forever()
