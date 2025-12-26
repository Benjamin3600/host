from fastapi import FastAPI
from pydantic import BaseModel
from database import get_conn

app = FastAPI()

# MODELS
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


# ------------------------
# SIGNUP
# ------------------------
@app.post("/push")
def signup(user: User):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("INSERT INTO users (username, password) VALUES (%s, %s)", 
                (user.username, user.password))
    
    conn.commit()
    cur.close()
    conn.close()

    return {"message": "Account created"}


# ------------------------
# LOGIN
# ------------------------
@app.post("/pull")
def login(user: User):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT username, password FROM users WHERE username=%s", 
                (user.username,))
    result = cur.fetchone()

    cur.close()
    conn.close()

    if result and result[1] == user.password:
        return {"username": result[0], "password": result[1]}
    else:
        return {"error": "Invalid login"}


# ------------------------
# SEND MESSAGE
# ------------------------
@app.post("/send")
def send_message(msg: Message):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        "INSERT INTO messages (sender, receiver, message) VALUES (%s, %s, %s)",
        (msg.sender, msg.receiver, msg.message)
    )

    conn.commit()
    cur.close()
    conn.close()

    return {"message": "Message sent"}


# ------------------------
# GET MESSAGES BETWEEN 2 USERS
# ------------------------
@app.post("/resp")
def get_messages(data: dict):
    sender = data["sender"]
    receiver = data["receiver"]

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, sender, receiver, message 
        FROM messages
        WHERE (sender=%s AND receiver=%s)
           OR (sender=%s AND receiver=%s)
        ORDER BY id ASC
    """, (sender, receiver, receiver, sender))

    rows = cur.fetchall()
    cur.close()
    conn.close()

    messages = [
        {"id": row[0], "sender": row[1], "receiver": row[2], "message": row[3]}
        for row in rows
    ]

    return messages


# ------------------------
# DELETE MESSAGE
# ------------------------
@app.post("/delete")
def delete_message(item: DeleteMsg):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("DELETE FROM messages WHERE id=%s AND sender=%s",
                (item.id, item.username))

    conn.commit()
    cur.close()
    conn.close()

    return {"message": "Deleted"}



@app.get("/search_users")
def search_users(q: str):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT username
        FROM users
        WHERE username ILIKE %s
        ORDER BY username
        LIMIT 20
        """,
        (f"%{q}%",)
    )

    results = cur.fetchall()

    cur.close()
    conn.close()

    return [row[0] for row in results]
