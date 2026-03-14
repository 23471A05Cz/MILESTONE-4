from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import uvicorn, os, socket, json

app = FastAPI()

# { ws: { "username": str, "room": str } }
clients: dict = {}


def find_free_port():
    for port in [4000, 4500, 5500, 6000, 6500, 7500, 9500, 9800]:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", port))
            s.close()
            return port
        except OSError:
            continue
    return 4000


@app.get("/")
async def home():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "m3.html")
    with open(path, "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.websocket("/ws")
async def ws_handler(ws: WebSocket):
    await ws.accept()

    try:
        while True:
            raw  = await ws.receive_text()
            try:
                data = json.loads(raw)
            except Exception:
                continue

            t = data.get("type", "")

            # ── JOIN ──────────────────────────────────────
            if t == "join":
                username = (data.get("username") or "Anonymous").strip()
                room     = (data.get("room") or "General").strip()

                # Register FIRST before any broadcast
                clients[ws] = {"username": username, "room": room}

                # Tell everyone else in the room someone joined
                await broadcast_others(ws, room, {
                    "type":     "joined",
                    "username": username,
                    "room":     room
                })

                # Update online list for everyone in room
                await send_online(room)

            # ── CHAT ──────────────────────────────────────
            elif t == "chat":
                if ws not in clients:
                    continue
                info   = clients[ws]
                msg_id = f"{id(ws)}_{abs(hash(raw))}"
                await broadcast_room(info["room"], {
                    "type":    "chat",
                    "id":      msg_id,
                    "user":    info["username"],
                    "message": data.get("message", ""),
                    "reply":   data.get("reply")
                })

            # ── TYPING ────────────────────────────────────
            # Broadcast to ALL in room INCLUDING the sender
            # so every open tab of the same user also sees the indicator
            elif t == "typing":
                if ws not in clients:
                    continue
                info = clients[ws]
                print(f"[TYPING] {info['username']} in {info['room']}")
                await broadcast_room(info["room"], {
                    "type": "typing",
                    "user": info["username"]
                })

            # ── STOP TYPING ───────────────────────────────
            elif t == "stop_typing":
                if ws not in clients:
                    continue
                info = clients[ws]
                print(f"[STOP]   {info['username']} in {info['room']}")
                await broadcast_room(info["room"], {
                    "type": "stop_typing",
                    "user": info["username"]
                })

            # ── REACT ─────────────────────────────────────
            elif t == "react":
                if ws not in clients:
                    continue
                info = clients[ws]
                await broadcast_room(info["room"], {
                    "type":  "react",
                    "msgId": data.get("msgId"),
                    "emoji": data.get("emoji"),
                    "user":  info["username"]
                })

            # ── SEEN ──────────────────────────────────────
            elif t == "seen":
                if ws not in clients:
                    continue
                info   = clients[ws]
                msg_id = data.get("msgId")
                for c, ci in list(clients.items()):
                    if ci["room"] == info["room"] and c is not ws:
                        try:
                            await c.send_json({"type": "seen", "msgId": msg_id})
                        except Exception:
                            pass

            # ── LEAVE ─────────────────────────────────────
            elif t == "leave":
                break

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[ERROR] {e}")
    finally:
        await _cleanup(ws)


async def _cleanup(ws: WebSocket):
    if ws in clients:
        info     = clients.pop(ws)
        room     = info["room"]
        username = info["username"]
        print(f"[LEAVE] {username} left {room}")
        # Clear typing state for this user
        await broadcast_room(room, {"type": "stop_typing", "user": username})
        await broadcast_room(room, {"type": "left", "username": username, "room": room})
        await send_online(room)


# ── HELPERS ──────────────────────────────────────────────

def room_members(room):
    return [c for c, i in clients.items() if i["room"] == room]


def get_online(room):
    return [i["username"] for c, i in clients.items() if i["room"] == room]


async def send_online(room):
    await broadcast_room(room, {"type": "online", "users": get_online(room)})


async def broadcast_room(room, data):
    """Send to ALL members in room — including the sender."""
    dead = []
    for c in room_members(room):
        try:
            await c.send_json(data)
        except Exception:
            dead.append(c)
    for c in dead:
        clients.pop(c, None)


async def broadcast_others(sender, room, data):
    """Send to all room members EXCEPT the sender."""
    dead = []
    for c in room_members(room):
        if c is sender:
            continue
        try:
            await c.send_json(data)
        except Exception:
            dead.append(c)
    for c in dead:
        clients.pop(c, None)


# ── ENTRY POINT ──────────────────────────────────────────

if __name__ == "__main__":
    PORT = find_free_port()
    print(f"""
╔══════════════════════════════════════════╗
║       🚀  Chatterbox  is  Running!       ║
╠══════════════════════════════════════════╣
║  🌐  http://localhost:{PORT}               ║
║  👥  Open multiple tabs to test          ║
║  ⌨️   Typing shows in ALL tabs  ✅        ║
╚══════════════════════════════════════════╝
""")
    uvicorn.run("m:app", host="0.0.0.0", port=PORT, reload=False)