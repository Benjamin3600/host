from fastapi import FastAPI
from pydantic import BaseModel
from database import get_conn
from fastapi import WebSocket, WebSocketDisconnect
import json
app = FastAPI()
class ConnectionManager:
    def __init__(self):
        # username → websocket
        self.active: dict[str, WebSocket] = {}

    async def connect(self, username: str, websocket: WebSocket):
        await websocket.accept()
        self.active[username] = websocket
        print(f"{username} connected (ws)")

    def disconnect(self, username: str):
        self.active.pop(username, None)
        print(f"{username} disconnected (ws)")

    async def send_private(self, to_user: str, message: str):
        ws = self.active.get(to_user)
        if ws:
            await ws.send_text(message)
manager = ConnectionManager()
# ---------------- MODELS ----------------
class User(BaseModel):
    username: str
    password: str

class Message(BaseModel):
    sender: str
    receiver: str
    message: str

class DeleteMsg(BaseModel):
    id: int
    username: str


# ---------------- SIGNUP ----------------
@app.post("/push")
def signup(user: User):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (username, password) VALUES (%s, %s)",
        (user.username, user.password)
    )
    conn.commit()
    cur.close()
    conn.close()
    return {"message": "Account created"}


# ---------------- LOGIN ----------------
@app.post("/pull")
def login(user: User):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT username, password FROM users WHERE username=%s",
        (user.username,)
    )
    result = cur.fetchone()
    cur.close()
    conn.close()

    if result and result[1] == user.password:
        return {"username": result[0], "password": result[1]}
    else:
        return {"error": "Invalid login"}


# ---------------- SEND MESSAGE ----------------
@app.post("/send")
def send_message(msg: Message):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO messages (sender, receiver, message) VALUES (%s, %s, %s) RETURNING id",
        (msg.sender, msg.receiver, msg.message)
    )
    message_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()

    message_data = {
        "id": message_id,
        "sender": msg.sender,
        "receiver": msg.receiver,
        "message": msg.message
    }

    # Real-time updates removed (no async, no WebSocket)
    return {"message": "Message sent", "id": message_id}


# ---------------- GET MESSAGES BETWEEN 2 USERS ----------------
@app.post("/resp")
def get_messages(data: dict):
    sender = data["sender"]
    receiver = data["receiver"]

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, sender, receiver, message,sent_time
        FROM messages
        WHERE (sender=%s AND receiver=%s)
           OR (sender=%s AND receiver=%s)
        ORDER BY id ASC
    """, (sender, receiver, receiver, sender))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    messages = [
        {"id": row[0], "sender": row[1], "receiver": row[2], "message": row[3], "sent_time": row[4].isoformat()}
        for row in rows
    ]
    return messages


# ---------------- DELETE MESSAGE ----------------
@app.post("/delete")
def delete_message(item: DeleteMsg):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        "DELETE FROM messages WHERE id=%s AND sender=%s",
        (item.id, item.username)
    )

    deleted = cur.rowcount
    conn.commit()

    cur.close()
    conn.close()

    if deleted == 0:
        return {"status": "failed", "reason": "Not found or not owner"}

    return {"status": "ok"}


# ---------------- SEARCH USERS ----------------
@app.get("/search_users")
def search_users(q: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT username
        FROM users
        WHERE username ILIKE %s
        ORDER BY username
        LIMIT 20
    """, (f"%{q}%",))
    results = cur.fetchall()
    cur.close()
    conn.close()
    return [row[0] for row in results]


# ---------------- INITIALIZE DB ----------------
@app.get("/init")
def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE,
            password TEXT
        );
        CREATE TABLE IF NOT EXISTS messages (
            id SERIAL PRIMARY KEY,
            sender TEXT,
            receiver TEXT,
            message TEXT,
            sent_time TIMESTAMP DEFAULT NOW()
        );
    """)
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "initialized"}

@app.get("/add")
def add_sent_time():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        ALTER TABLE messages
        ADD COLUMN IF NOT EXISTS sent_time TIMESTAMP DEFAULT NOW();
    """)
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "column added"}



@app.websocket("/ws/chat/{username}")
async def websocket_chat(websocket: WebSocket, username: str):
    await manager.connect(username, websocket)

    try:
        while True:
            raw = await websocket.receive_text()
            data = json.loads(raw)

            # =========================================
            # SEND MESSAGE
            # =========================================
            if data["type"] == "message":

                receiver = data["receiver"]
                message = data["message"]

                # ---- STORE FIRST ----
                conn = get_conn()
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO messages (sender, receiver, message)
                    VALUES (%s, %s, %s)
                    RETURNING id, sent_time
                    """,
                    (username, receiver, message)
                )
                msg_id, sent_time = cur.fetchone()
                conn.commit()
                cur.close()
                conn.close()

                payload = {
                    "type": "message",
                    "id": msg_id,
                    "sender": username,
                    "receiver": receiver,
                    "message": message,
                    "sent_time": sent_time.isoformat()
                }

                # ---- SEND TO RECEIVER ----
                await manager.send_private(receiver, json.dumps(payload))

                # ---- ALSO SEND BACK TO SENDER ----
                await manager.send_private(username, json.dumps(payload))


            # =========================================
            # DELETE MESSAGE
            # =========================================
            # =========================================
            elif data["type"] == "delete":

                msg_id = int(data["id"])

                conn = get_conn()
                cur = conn.cursor()

    # Get receiver BEFORE deleting
                cur.execute(
        "SELECT receiver FROM messages WHERE id=%s AND sender=%s",
        (msg_id, username)
    )
                row = cur.fetchone()

                if not row:
                    cur.close()
                    conn.close()
                    continue

                receiver = row[0]

    # Now delete
                cur.execute(
        "DELETE FROM messages WHERE id=%s AND sender=%s",
        (msg_id, username)
    )
                conn.commit()

                cur.close()
                conn.close()

                payload = {
        "type": "delete",
        "id": msg_id
    }

    # Notify BOTH users
                await manager.send_private(username, json.dumps(payload))
                await manager.send_private(receiver, json.dumps(payload))

    except WebSocketDisconnect:
        manager.disconnect(username)
