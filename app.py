"""
Post It — fun, messy, Facebook-style social platform (prototype v1).

Run:  ./venv/bin/uvicorn app:app --host 127.0.0.1 --port 8001
DB:   postit.db in this directory (SQLite).
Uploads: uploads/ in this directory, served at /uploads.

Everything in v1 is free-tier: no SMS, no payments. The $5/mo verified
subscription endpoint exists but is DISABLED by default behind the
STRIPE_VERIFIED_ENABLED env flag (UI shows "coming soon").
"""
import os
import re
import secrets
import shutil
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("POSTIT_DB", os.path.join(BASE, "postit.db"))
UPLOAD_DIR = os.environ.get("POSTIT_UPLOADS", os.path.join(BASE, "uploads"))
GOAL_HIDDEN = "/home/hatch/workspace/goals/post-it-social-platform/hidden_files"
ADMIN_CRED_FILE = os.path.join(GOAL_HIDDEN, "admin-credentials.txt")

STRIPE_VERIFIED_ENABLED = os.environ.get("STRIPE_VERIFIED_ENABLED", "").strip() == "1"

CATEGORIES = ["Cars", "Home Decor", "Clothing", "Shoes", "Games", "Electronics", "Other"]
NOTE_COLORS = ["#fff3a3", "#ffb3d9", "#ff8a8a", "#a3d8ff", "#b3ffb3", "#d9b3ff",
               "#ffd1a3", "#1a1a1a"]
REACTION_KINDS = ["like", "love", "laugh", "fire", "skull"]

IMG_EXTS = {"jpg", "jpeg", "png", "gif", "webp"}
VID_EXTS = {"mp4", "mov", "webm"}
AUD_EXTS = {"mp3", "wav", "ogg", "m4a"}
MAX_UPLOAD_MB = 50

for _d in ("avatars", "covers", "posts", "stories", "market"):
    os.makedirs(os.path.join(UPLOAD_DIR, _d), exist_ok=True)

app = FastAPI(title="Post It")
app.mount("/static", StaticFiles(directory=os.path.join(BASE, "static")), name="static")
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
templates = Jinja2Templates(directory=os.path.join(BASE, "templates"))


def fancy_time(value):
    """Render a stored timestamp as friendly text like 'Oct 11, 2026 · 6:44 PM'."""
    if not value:
        return ""
    dt = None
    if isinstance(value, datetime):
        dt = value
    else:
        v = str(value).strip()
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S",
                    "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
            try:
                dt = datetime.strptime(v, fmt)
                break
            except ValueError:
                pass
        if dt is None:
            try:
                dt = datetime.fromisoformat(v)
            except Exception:
                return value
    return dt.strftime("%b %-d, %Y \u00b7 %-I:%M %p")


templates.env.filters["fancy_time"] = fancy_time


# ---------------- DB ----------------
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL, email TEXT NOT NULL UNIQUE, pw_hash TEXT NOT NULL,
        world_title TEXT DEFAULT '', bio TEXT DEFAULT '', birthday TEXT DEFAULT '',
        hometown TEXT DEFAULT '', city TEXT DEFAULT '', workplace TEXT DEFAULT '',
        job_title TEXT DEFAULT '', avatar TEXT DEFAULT '', cover TEXT DEFAULT '',
        verified INTEGER DEFAULT 0, is_blocked INTEGER DEFAULT 0,
        created_at TEXT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS sessions (
        token TEXT PRIMARY KEY, user_id INTEGER NOT NULL, created_at TEXT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS admin_sessions (
        token TEXT PRIMARY KEY, created_at TEXT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS friendships (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL, friend_id INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL,
        UNIQUE(user_id, friend_id))""")
    c.execute("""CREATE TABLE IF NOT EXISTS posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL, kind TEXT NOT NULL DEFAULT 'text',
        body TEXT DEFAULT '', media TEXT DEFAULT '', color TEXT DEFAULT '#fff3a3',
        privacy TEXT NOT NULL DEFAULT 'public',
        allow_list TEXT DEFAULT '', deny_list TEXT DEFAULT '',
        shared_from INTEGER DEFAULT 0, archived INTEGER DEFAULT 0,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
        body TEXT NOT NULL, created_at TEXT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS reactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id INTEGER NOT NULL, user_id INTEGER NOT NULL, kind TEXT NOT NULL,
        created_at TEXT NOT NULL, UNIQUE(post_id, user_id, kind))""")
    c.execute("""CREATE TABLE IF NOT EXISTS stories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL, media TEXT NOT NULL, kind TEXT NOT NULL,
        created_at TEXT NOT NULL, expires_at TEXT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender_id INTEGER NOT NULL, recipient_id INTEGER NOT NULL,
        body TEXT NOT NULL, created_at TEXT NOT NULL, read INTEGER DEFAULT 0)""")
    c.execute("""CREATE TABLE IF NOT EXISTS blocks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        blocker_id INTEGER NOT NULL, blocked_id INTEGER NOT NULL,
        created_at TEXT NOT NULL, UNIQUE(blocker_id, blocked_id))""")
    c.execute("""CREATE TABLE IF NOT EXISTS market_listings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL, title TEXT NOT NULL, category TEXT DEFAULT 'Other',
        price REAL DEFAULT 0, description TEXT DEFAULT '', photos TEXT DEFAULT '[]',
        shipping INTEGER DEFAULT 0, meetup_city TEXT DEFAULT '',
        status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS market_groups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL, description TEXT DEFAULT '',
        owner_id INTEGER NOT NULL, created_at TEXT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS group_members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
        created_at TEXT NOT NULL, UNIQUE(group_id, user_id))""")
    c.execute("""CREATE TABLE IF NOT EXISTS group_posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
        body TEXT NOT NULL, created_at TEXT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS offers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        listing_id INTEGER NOT NULL, buyer_id INTEGER NOT NULL,
        amount REAL NOT NULL, message TEXT DEFAULT '',
        status TEXT NOT NULL DEFAULT 'open', created_at TEXT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS ratings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        seller_id INTEGER NOT NULL, rater_id INTEGER NOT NULL,
        stars INTEGER NOT NULL, comment TEXT DEFAULT '',
        created_at TEXT NOT NULL, UNIQUE(seller_id, rater_id))""")
    c.execute("""CREATE TABLE IF NOT EXISTS iso_posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL, title TEXT NOT NULL,
        description TEXT DEFAULT '', category TEXT DEFAULT 'Other',
        max_price REAL DEFAULT 0, created_at TEXT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        reporter_id INTEGER NOT NULL, target_type TEXT NOT NULL,
        target_id INTEGER NOT NULL, reason TEXT DEFAULT '',
        status TEXT NOT NULL DEFAULT 'open', created_at TEXT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY, value TEXT)""")
    conn.commit()
    conn.close()
    _ensure_admin_password()


def _ensure_admin_password():
    """Admin password: ADMIN_PASSWORD env wins (Render). Otherwise generate a
    strong random password once; store hash in DB and the plaintext in the
    goal's hidden files (never in the repo)."""
    env_pw = os.environ.get("ADMIN_PASSWORD", "")
    os.makedirs(GOAL_HIDDEN, exist_ok=True)
    conn = db()
    row = conn.execute("SELECT value FROM settings WHERE key='admin_pw_hash'").fetchone()
    if row:
        conn.close()
        return
    pw = env_pw if env_pw else secrets.token_urlsafe(18)
    pw_hash = bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()
    conn.execute("INSERT INTO settings(key, value) VALUES('admin_pw_hash', ?)", (pw_hash,))
    conn.commit()
    conn.close()
    if not env_pw:
        with open(ADMIN_CRED_FILE, "w") as f:
            f.write("Post It admin panel\n")
            f.write("URL: /admin  (local prototype: http://127.0.0.1:8001/admin)\n")
            f.write("Username: admin\n")
            f.write(f"Password: {pw}\n")
            f.write("Generated once at first startup. Keep this file private.\n")
        os.chmod(ADMIN_CRED_FILE, 0o600)


init_db()


# ---------------- helpers ----------------
def now_iso():
    return datetime.now(timezone.utc).isoformat()


def fmt(ts):
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone().strftime("%b %d, %Y %I:%M %p").replace(" 0", " ")
    except Exception:
        return ts or ""


def row_to_dict(r):
    return dict(r) if r else None


def get_user(uid):
    if not uid:
        return None
    conn = db()
    r = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    conn.close()
    return row_to_dict(r)


def current_user(request: Request):
    token = request.cookies.get("postit_session", "")
    if not token:
        return None
    conn = db()
    s = conn.execute("SELECT user_id FROM sessions WHERE token=?", (token,)).fetchone()
    conn.close()
    if not s:
        return None
    u = get_user(s["user_id"])
    if u and u["is_blocked"]:
        return None
    return u


def is_admin(request: Request):
    token = request.cookies.get("postit_admin", "")
    if not token:
        return False
    conn = db()
    s = conn.execute("SELECT token FROM admin_sessions WHERE token=?", (token,)).fetchone()
    conn.close()
    return bool(s)


def render(request, name, ctx=None):
    ctx = dict(ctx or {})
    u = current_user(request)
    ctx.setdefault("user", u)
    ctx.setdefault("logo_url", "/static/logo.png")
    ctx.setdefault("flash", request.query_params.get("flash", ""))
    ctx.setdefault("verified_enabled", 1 if STRIPE_VERIFIED_ENABLED else 0)
    if u:
        conn = db()
        cnt = conn.execute(
            "SELECT COUNT(*) c FROM messages WHERE recipient_id=? AND read=0",
            (u["id"],)).fetchone()["c"]
        pr = conn.execute(
            "SELECT COUNT(*) c FROM friendships WHERE friend_id=? AND status='pending'",
            (u["id"],)).fetchone()["c"]
        conn.close()
        ctx.setdefault("unread_count", cnt)
        ctx.setdefault("pending_reqs", pr)
    else:
        ctx.setdefault("unread_count", 0)
        ctx.setdefault("pending_reqs", 0)
    return templates.TemplateResponse(request, name, ctx)


def redir(url, flash=""):
    if flash:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}flash={flash}"
    return RedirectResponse(url, status_code=303)


def require_login(request):
    u = current_user(request)
    if not u:
        return None, redir("/login", "Please log in first.")
    return u, None


def is_blocked_either(a, b):
    if not a or not b:
        return False
    conn = db()
    r = conn.execute(
        "SELECT 1 FROM blocks WHERE (blocker_id=? AND blocked_id=?) OR (blocker_id=? AND blocked_id=?)",
        (a, b, b, a)).fetchone()
    conn.close()
    return bool(r)


def are_friends(a, b):
    if not a or not b or a == b:
        return a == b
    conn = db()
    r = conn.execute(
        """SELECT 1 FROM friendships
           WHERE ((user_id=? AND friend_id=?) OR (user_id=? AND friend_id=?))
           AND status='accepted'""", (a, b, b, a)).fetchone()
    conn.close()
    return bool(r)


def friend_ids(uid):
    conn = db()
    rows = conn.execute(
        """SELECT CASE WHEN user_id=? THEN friend_id ELSE user_id END AS fid
           FROM friendships WHERE (user_id=? OR friend_id=?) AND status='accepted'""",
        (uid, uid, uid)).fetchall()
    conn.close()
    return [r["fid"] for r in rows]


def _id_list(s):
    out = []
    for part in (s or "").replace(";", ",").split(","):
        part = part.strip()
        if part.isdigit():
            out.append(int(part))
    return out


def can_view_post(viewer_id, p):
    """p is a post row dict."""
    owner = p["user_id"]
    if viewer_id == owner:
        return True
    if p["archived"]:
        return False
    if is_blocked_either(viewer_id, owner):
        return False
    priv = p["privacy"]
    if priv == "public":
        return True
    if priv == "friends":
        return are_friends(viewer_id, owner)
    if priv == "me":
        return False
    if priv == "custom":
        allow = _id_list(p["allow_list"])
        deny = _id_list(p["deny_list"])
        if viewer_id in deny:
            return False
        if allow and viewer_id not in allow:
            return False
        return True
    return False


def post_card_dict(p, viewer_id, with_comments=False):
    conn = db()
    author = conn.execute("SELECT id, name, avatar, verified, world_title FROM users WHERE id=?",
                          (p["user_id"],)).fetchone()
    counts = {k: 0 for k in REACTION_KINDS}
    for r in conn.execute("SELECT kind, COUNT(*) c FROM reactions WHERE post_id=? GROUP BY kind",
                          (p["id"],)):
        counts[r["kind"]] = r["c"]
    my_reaction = ""
    cc = 0
    comments = []
    shared = None
    if viewer_id:
        mr = conn.execute("SELECT kind FROM reactions WHERE post_id=? AND user_id=?",
                          (p["id"], viewer_id)).fetchone()
        if mr:
            my_reaction = mr["kind"]
    cc = conn.execute("SELECT COUNT(*) c FROM comments WHERE post_id=?", (p["id"],)).fetchone()["c"]
    if with_comments:
        for c in conn.execute(
                """SELECT comments.*, users.name AS author_name, users.avatar AS author_avatar,
                          users.verified AS verified
                   FROM comments JOIN users ON users.id=comments.user_id
                   WHERE post_id=? ORDER BY created_at ASC""", (p["id"],)):
            d = row_to_dict(c)
            d["created_display"] = fmt(d["created_at"])
            comments.append(d)
    if p["shared_from"]:
        orig = conn.execute("SELECT * FROM posts WHERE id=?", (p["shared_from"],)).fetchone()
        if orig:
            od = row_to_dict(orig)
            oa = conn.execute("SELECT name, verified FROM users WHERE id=?",
                              (od["user_id"],)).fetchone()
            shared = {"id": od["id"], "author_name": oa["name"] if oa else "?",
                      "verified": oa["verified"] if oa else 0,
                      "body": od["body"], "media": od["media"], "kind": od["kind"]}
    conn.close()
    d = dict(p)
    d["author_name"] = author["name"] if author else "?"
    d["author_avatar"] = author["avatar"] if author else ""
    d["verified"] = author["verified"] if author else 0
    d["world_title"] = author["world_title"] if author else ""
    d["counts"] = counts
    d["my_reaction"] = my_reaction
    d["comments_count"] = cc
    d["comments"] = comments
    d["shared"] = shared
    d["created_display"] = fmt(p["created_at"])
    d["is_owner"] = (viewer_id == p["user_id"])
    d["can_edit"] = d["is_owner"]
    d["can_delete"] = d["is_owner"]
    return d


def save_upload(file, subdir):
    """Save an UploadFile; return (url, kind) or (None, None)."""
    if not file or not getattr(file, "filename", ""):
        return None, None
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    data = file.file.read()
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        return None, None
    name = f"{uuid.uuid4().hex}.{ext}"
    path = os.path.join(UPLOAD_DIR, subdir, name)
    with open(path, "wb") as f:
        f.write(data)
    url = f"/uploads/{subdir}/{name}"
    if ext in IMG_EXTS:
        kind = "photo"
    elif ext in VID_EXTS:
        kind = "video"
    elif ext in AUD_EXTS:
        kind = "audio"
    else:
        os.remove(path)
        return None, None
    return url, kind


# ---------------- landing / auth ----------------
@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    if current_user(request):
        return redir("/home")
    return redir("/login")


@app.get("/signup", response_class=HTMLResponse)
def signup_page(request: Request):
    if current_user(request):
        return redir("/home")
    return render(request, "auth/signup.html")


@app.post("/signup")
async def signup(request: Request):
    form = await request.form()
    name = (form.get("name") or "").strip()[:80]
    email = (form.get("email") or "").strip().lower()[:160]
    password = form.get("password") or ""
    if not name or not email or len(password) < 4:
        return render(request, "auth/signup.html",
                      {"flash": "Name, email, and a 4+ character password are required."})
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return render(request, "auth/signup.html", {"flash": "That email doesn't look right."})
    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    conn = db()
    try:
        cur = conn.execute(
            "INSERT INTO users(name, email, pw_hash, world_title, created_at) VALUES(?,?,?,?,?)",
            (name, email, pw_hash, f"{name}'s World", now_iso()))
        uid = cur.lastrowid
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return render(request, "auth/signup.html", {"flash": "That email is already registered."})
    token = secrets.token_urlsafe(32)
    conn.execute("INSERT INTO sessions(token, user_id, created_at) VALUES(?,?,?)",
                 (token, uid, now_iso()))
    conn.commit()
    conn.close()
    resp = redir("/home", f"Welcome to Post It, {name}!")
    resp.set_cookie("postit_session", token, httponly=True, max_age=30 * 86400, samesite="lax")
    return resp


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if current_user(request):
        return redir("/home")
    return render(request, "auth/login.html")


@app.post("/login")
async def login(request: Request):
    form = await request.form()
    email = (form.get("email") or "").strip().lower()
    password = form.get("password") or ""
    conn = db()
    r = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    conn.close()
    u = row_to_dict(r)
    if not u or not bcrypt.checkpw(password.encode(), u["pw_hash"].encode()):
        return render(request, "auth/login.html", {"flash": "Wrong email or password."})
    if u["is_blocked"]:
        return render(request, "auth/login.html", {"flash": "This account has been blocked."})
    token = secrets.token_urlsafe(32)
    conn = db()
    conn.execute("INSERT INTO sessions(token, user_id, created_at) VALUES(?,?,?)",
                 (token, u["id"], now_iso()))
    conn.commit()
    conn.close()
    resp = redir("/home", f"Welcome back, {u['name']}!")
    resp.set_cookie("postit_session", token, httponly=True, max_age=30 * 86400, samesite="lax")
    return resp


@app.get("/logout")
def logout(request: Request):
    token = request.cookies.get("postit_session", "")
    if token:
        conn = db()
        conn.execute("DELETE FROM sessions WHERE token=?", (token,))
        conn.commit()
        conn.close()
    resp = redir("/login", "Logged out. See you soon!")
    resp.delete_cookie("postit_session")
    return resp


# ---------------- home / feed ----------------
@app.get("/home", response_class=HTMLResponse)
def home(request: Request):
    u, err = require_login(request)
    if err:
        return err
    conn = db()
    # expire old stories
    conn.execute("DELETE FROM stories WHERE expires_at <= ?", (now_iso(),))
    conn.commit()
    fids = friend_ids(u["id"])
    ids = fids + [u["id"]]
    ph = ",".join("?" * len(ids))
    posts = []
    for p in conn.execute(
            f"SELECT * FROM posts WHERE user_id IN ({ph}) AND archived=0 "
            f"ORDER BY created_at DESC LIMIT 100", ids):
        pd = row_to_dict(p)
        if can_view_post(u["id"], pd):
            posts.append(post_card_dict(pd, u["id"]))
    stories = []
    for s in conn.execute(
            f"""SELECT stories.*, users.name AS user_name, users.avatar AS avatar,
                       users.verified AS verified
                FROM stories JOIN users ON users.id=stories.user_id
                WHERE stories.user_id IN ({ph}) AND users.is_blocked=0
                ORDER BY stories.created_at DESC""", ids):
        stories.append(row_to_dict(s))
    conn.close()
    return render(request, "home.html", {"posts": posts, "stories": stories,
                                         "note_colors": NOTE_COLORS})


@app.post("/posts")
async def create_post(request: Request):
    u, err = require_login(request)
    if err:
        return err
    form = await request.form()
    body = (form.get("body") or "").strip()[:5000]
    color = (form.get("color") or "#fff3a3").strip()
    if color not in NOTE_COLORS:
        color = "#fff3a3"
    privacy = (form.get("privacy") or "public").strip()
    if privacy not in ("public", "friends", "me", "custom"):
        privacy = "public"
    allow = (form.get("allow") or "").strip()[:500]
    deny = (form.get("deny") or "").strip()[:500]
    media_url, kind = save_upload(form.get("media"), "posts")
    if not body and not media_url:
        return redir("/home", "Write something or attach a photo first!")
    if not kind:
        kind = "text"
    conn = db()
    conn.execute(
        """INSERT INTO posts(user_id, kind, body, media, color, privacy,
                             allow_list, deny_list, created_at, updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (u["id"], kind, body, media_url or "", color, privacy, allow, deny,
         now_iso(), now_iso()))
    conn.commit()
    conn.close()
    return redir("/home", "Stuck on the wall! 📌")


@app.get("/post/{pid}", response_class=HTMLResponse)
def post_detail(request: Request, pid: int):
    u, err = require_login(request)
    if err:
        return err
    conn = db()
    r = conn.execute("SELECT * FROM posts WHERE id=?", (pid,)).fetchone()
    conn.close()
    if not r:
        return redir("/home", "That note is gone.")
    p = row_to_dict(r)
    if not can_view_post(u["id"], p):
        return redir("/home", "You can't see that note.")
    return render(request, "post.html", {"post": post_card_dict(p, u["id"], with_comments=True)})


@app.post("/post/{pid}/edit")
async def edit_post(request: Request, pid: int):
    u, err = require_login(request)
    if err:
        return err
    form = await request.form()
    body = (form.get("body") or "").strip()[:5000]
    conn = db()
    p = conn.execute("SELECT * FROM posts WHERE id=?", (pid,)).fetchone()
    if not p or p["user_id"] != u["id"]:
        conn.close()
        return redir("/home", "Not your note to edit.")
    conn.execute("UPDATE posts SET body=?, updated_at=? WHERE id=?", (body, now_iso(), pid))
    conn.commit()
    conn.close()
    return redir(f"/post/{pid}", "Note updated.")


@app.post("/post/{pid}/delete")
async def delete_post(request: Request, pid: int):
    u, err = require_login(request)
    if err:
        return err
    conn = db()
    p = conn.execute("SELECT * FROM posts WHERE id=?", (pid,)).fetchone()
    if not p or p["user_id"] != u["id"]:
        conn.close()
        return redir("/home", "Not your note to delete.")
    if p["media"]:
        try:
            os.remove(os.path.join(BASE, p["media"].lstrip("/")))
        except OSError:
            pass
    conn.execute("DELETE FROM reactions WHERE post_id=?", (pid,))
    conn.execute("DELETE FROM comments WHERE post_id=?", (pid,))
    conn.execute("DELETE FROM posts WHERE id=?", (pid,))
    conn.commit()
    conn.close()
    return redir("/home", "Note peeled off the wall.")


@app.post("/post/{pid}/comment")
async def comment_post(request: Request, pid: int):
    u, err = require_login(request)
    if err:
        return err
    form = await request.form()
    body = (form.get("body") or "").strip()[:2000]
    conn = db()
    p = conn.execute("SELECT * FROM posts WHERE id=?", (pid,)).fetchone()
    conn.close()
    if not p or not body:
        return redir(f"/post/{pid}")
    pd = row_to_dict(p)
    if not can_view_post(u["id"], pd):
        return redir("/home", "You can't see that note.")
    conn = db()
    conn.execute("INSERT INTO comments(post_id, user_id, body, created_at) VALUES(?,?,?,?)",
                 (pid, u["id"], body, now_iso()))
    conn.commit()
    conn.close()
    return redir(f"/post/{pid}")


@app.post("/post/{pid}/react")
async def react_post(request: Request, pid: int):
    u, err = require_login(request)
    if err:
        return JSONResponse({"ok": False, "error": "login"}, status_code=401)
    form = await request.form()
    kind = (form.get("kind") or "").strip()
    if kind not in REACTION_KINDS:
        return JSONResponse({"ok": False}, status_code=400)
    conn = db()
    p = conn.execute("SELECT * FROM posts WHERE id=?", (pid,)).fetchone()
    if not p:
        conn.close()
        return JSONResponse({"ok": False}, status_code=404)
    if not can_view_post(u["id"], row_to_dict(p)):
        conn.close()
        return JSONResponse({"ok": False}, status_code=403)
    existing = conn.execute("SELECT kind FROM reactions WHERE post_id=? AND user_id=?",
                            (pid, u["id"])).fetchone()
    if existing and existing["kind"] == kind:
        conn.execute("DELETE FROM reactions WHERE post_id=? AND user_id=? AND kind=?",
                     (pid, u["id"], kind))
        my_reaction = ""
    else:
        conn.execute("DELETE FROM reactions WHERE post_id=? AND user_id=?", (pid, u["id"]))
        conn.execute("INSERT INTO reactions(post_id, user_id, kind, created_at) VALUES(?,?,?,?)",
                     (pid, u["id"], kind, now_iso()))
        my_reaction = kind
    conn.commit()
    counts = {k: 0 for k in REACTION_KINDS}
    for r in conn.execute("SELECT kind, COUNT(*) c FROM reactions WHERE post_id=? GROUP BY kind",
                          (pid,)):
        counts[r["kind"]] = r["c"]
    conn.close()
    return JSONResponse({"ok": True, "counts": counts, "my_reaction": my_reaction})


@app.post("/post/{pid}/share")
async def share_post(request: Request, pid: int):
    u, err = require_login(request)
    if err:
        return err
    conn = db()
    p = conn.execute("SELECT * FROM posts WHERE id=?", (pid,)).fetchone()
    if not p:
        conn.close()
        return redir("/home", "That note is gone.")
    pd = row_to_dict(p)
    if not can_view_post(u["id"], pd):
        conn.close()
        return redir("/home", "You can't see that note.")
    conn.execute(
        """INSERT INTO posts(user_id, kind, body, media, color, privacy, shared_from,
                             created_at, updated_at)
           VALUES(?, 'text', '', '', '#fff3a3', 'public', ?, ?, ?)""",
        (u["id"], pid, now_iso(), now_iso()))
    conn.commit()
    conn.close()
    return redir("/home", "Shared to your wall! 📌")


@app.post("/post/{pid}/report")
async def report_post(request: Request, pid: int):
    u, err = require_login(request)
    if err:
        return err
    form = await request.form()
    reason = (form.get("reason") or "").strip()[:500]
    conn = db()
    conn.execute(
        "INSERT INTO reports(reporter_id, target_type, target_id, reason, created_at) "
        "VALUES(?,?,?,?,?)", (u["id"], "post", pid, reason or "No reason given", now_iso()))
    conn.commit()
    conn.close()
    return redir(f"/post/{pid}", "Reported. The Post It team will take a look.")


# ---------------- stories ----------------
@app.post("/stories")
async def create_story(request: Request):
    u, err = require_login(request)
    if err:
        return err
    form = await request.form()
    media_url, kind = save_upload(form.get("media"), "stories")
    if not media_url:
        return redir("/home", "Pick a photo or video for your story.")
    if kind == "audio":
        kind = "photo"
    conn = db()
    conn.execute("INSERT INTO stories(user_id, media, kind, created_at, expires_at) "
                 "VALUES(?,?,?,?,?)",
                 (u["id"], media_url, kind, now_iso(),
                  (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()))
    conn.commit()
    conn.close()
    return redir("/home", "Story's up for 24 hours! ⏳")


@app.get("/stories/{sid}", response_class=HTMLResponse)
def view_story(request: Request, sid: int):
    u, err = require_login(request)
    if err:
        return err
    conn = db()
    s = conn.execute(
        """SELECT stories.*, users.name AS user_name, users.avatar AS avatar,
                  users.verified AS verified, users.id AS user_id
           FROM stories JOIN users ON users.id=stories.user_id
           WHERE stories.id=? AND stories.expires_at > ?""",
        (sid, now_iso())).fetchone()
    conn.close()
    if not s:
        return redir("/home", "That story expired.")
    return render(request, "story.html", {"story": row_to_dict(s)})


# ---------------- profile / world ----------------
@app.get("/world/{uid}", response_class=HTMLResponse)
def world(request: Request, uid: int):
    u, err = require_login(request)
    if err:
        return err
    profile = get_user(uid)
    if not profile or profile["is_blocked"]:
        return redir("/home", "That world doesn't exist.")
    if is_blocked_either(u["id"], uid) and u["id"] != uid:
        return redir("/home", "You can't visit that world.")
    conn = db()
    posts = []
    for p in conn.execute(
            "SELECT * FROM posts WHERE user_id=? AND archived=0 ORDER BY created_at DESC LIMIT 100",
            (uid,)):
        pd = row_to_dict(p)
        if can_view_post(u["id"], pd):
            posts.append(post_card_dict(pd, u["id"]))
    fr = conn.execute(
        """SELECT * FROM friendships
           WHERE (user_id=? AND friend_id=?) OR (user_id=? AND friend_id=?)""",
        (u["id"], uid, uid, u["id"])).fetchone()
    if u["id"] == uid:
        req_status = "self"
    elif not fr:
        req_status = "none"
    elif fr["status"] == "accepted":
        req_status = "friends"
    elif fr["user_id"] == u["id"]:
        req_status = "pending_out"
    else:
        req_status = "pending_in"
    blocked_by_me = bool(conn.execute(
        "SELECT 1 FROM blocks WHERE blocker_id=? AND blocked_id=?",
        (u["id"], uid)).fetchone())
    friend_count = conn.execute(
        """SELECT COUNT(*) c FROM friendships
           WHERE (user_id=? OR friend_id=?) AND status='accepted'""",
        (uid, uid)).fetchone()["c"]
    my_friends = []
    if u["id"] != uid:
        for f in conn.execute(
                """SELECT users.id, users.name, users.avatar, users.verified
                   FROM friendships
                   JOIN users ON users.id = CASE WHEN friendships.user_id=?
                         THEN friendships.friend_id ELSE friendships.user_id END
                   WHERE (friendships.user_id=? OR friendships.friend_id=?)
                   AND status='accepted' AND users.is_blocked=0
                   AND users.id != ?""",
                (u["id"], u["id"], u["id"], uid)):
            my_friends.append(row_to_dict(f))
    conn.close()
    profile["friend_count"] = friend_count
    return render(request, "profile.html",
                  {"profile": profile, "posts": posts, "req_status": req_status,
                   "blocked_by_me": blocked_by_me,
                   "is_owner": u["id"] == uid,
                   "my_friends": my_friends})


@app.get("/settings/profile", response_class=HTMLResponse)
def profile_edit_page(request: Request):
    u, err = require_login(request)
    if err:
        return err
    return render(request, "profile_edit.html", {"profile": get_user(u["id"])})


@app.post("/settings/profile")
async def profile_edit(request: Request):
    u, err = require_login(request)
    if err:
        return err
    form = await request.form()
    fields = {}
    for key in ("world_title", "name", "bio", "birthday", "hometown", "city",
                "workplace", "job_title"):
        fields[key] = (form.get(key) or "").strip()[:300]
    if not fields["name"]:
        return redir("/settings/profile", "Name can't be blank.")
    avatar_url, _ = save_upload(form.get("avatar"), "avatars")
    cover_url, _ = save_upload(form.get("cover"), "covers")
    conn = db()
    old = conn.execute("SELECT avatar, cover FROM users WHERE id=?", (u["id"],)).fetchone()
    if avatar_url and old["avatar"]:
        try:
            os.remove(os.path.join(BASE, old["avatar"].lstrip("/")))
        except OSError:
            pass
    if cover_url and old["cover"]:
        try:
            os.remove(os.path.join(BASE, old["cover"].lstrip("/")))
        except OSError:
            pass
    sets = ", ".join(f"{k}=?" for k in fields) + ", avatar=?, cover=?"
    vals = list(fields.values())
    vals.append(avatar_url or old["avatar"])
    vals.append(cover_url or old["cover"])
    vals.append(u["id"])
    conn.execute(f"UPDATE users SET {sets} WHERE id=?", vals)
    conn.commit()
    conn.close()
    return redir(f"/world/{u['id']}", "Your world is updated! 🌍")


# ---------------- friends ----------------
@app.post("/world/{uid}/share")
async def share_world(request: Request, uid: int):
    u, err = require_login(request)
    if err:
        return err
    form = await request.form()
    try:
        fid = int(form.get("friend_id") or 0)
    except ValueError:
        fid = 0
    target = get_user(uid)
    if not target or target["is_blocked"] or not fid or fid == uid:
        return redir(f"/world/{uid}", "Couldn't share that world.")
    conn = db()
    ok = conn.execute(
        """SELECT 1 FROM friendships
           WHERE ((user_id=? AND friend_id=?) OR (user_id=? AND friend_id=?))
           AND status='accepted'""",
        (u["id"], fid, fid, u["id"])).fetchone()
    if not ok or is_blocked_either(u["id"], fid):
        conn.close()
        return redir(f"/world/{uid}", "You can only share with your friends.")
    conn.execute(
        "INSERT INTO messages(sender_id, recipient_id, body, created_at) VALUES(?,?,?,?)",
        (u["id"], fid,
         f"🌍 {u['name']} shared a world with you: {target['name']}'s “{target['world_title']}” — /world/{uid}",
         now_iso()))
    conn.commit()
    conn.close()
    return redir(f"/world/{uid}", f"Shared {target['name']}'s world! 🌍")
@app.get("/friends", response_class=HTMLResponse)
def friends_page(request: Request):
    u, err = require_login(request)
    if err:
        return err
    conn = db()
    incoming, sent, friends = [], [], []
    for f in conn.execute(
            """SELECT friendships.*, users.name, users.avatar, users.verified
               FROM friendships JOIN users ON users.id=friendships.user_id
               WHERE friend_id=? AND status='pending'""", (u["id"],)):
        incoming.append(row_to_dict(f))
    for f in conn.execute(
            """SELECT friendships.*, users.name, users.avatar, users.verified
               FROM friendships JOIN users ON users.id=friendships.friend_id
               WHERE user_id=? AND status='pending'""", (u["id"],)):
        sent.append(row_to_dict(f))
    for f in conn.execute(
            """SELECT users.id, users.name, users.avatar, users.verified, users.world_title
               FROM friendships
               JOIN users ON users.id = CASE WHEN friendships.user_id=?
                     THEN friendships.friend_id ELSE friendships.user_id END
               WHERE (friendships.user_id=? OR friendships.friend_id=?)
               AND status='accepted' AND users.is_blocked=0""",
            (u["id"], u["id"], u["id"])):
        friends.append(row_to_dict(f))
    conn.close()
    return render(request, "friends.html",
                  {"incoming": incoming, "sent": sent, "friends": friends})


@app.post("/friends/request/{uid}")
async def friend_request(request: Request, uid: int):
    u, err = require_login(request)
    if err:
        return err
    if uid == u["id"]:
        return redir(f"/world/{uid}")
    if is_blocked_either(u["id"], uid):
        return redir(f"/world/{uid}", "You can't friend this person.")
    conn = db()
    conn.execute(
        "INSERT OR IGNORE INTO friendships(user_id, friend_id, status, created_at) "
        "VALUES(?,?, 'pending', ?)", (u["id"], uid, now_iso()))
    conn.commit()
    conn.close()
    return redir(f"/world/{uid}", "Friend request sent! 🤝")


@app.post("/friends/accept/{uid}")
async def friend_accept(request: Request, uid: int):
    u, err = require_login(request)
    if err:
        return err
    conn = db()
    conn.execute(
        "UPDATE friendships SET status='accepted' WHERE user_id=? AND friend_id=? AND status='pending'",
        (uid, u["id"]))
    conn.commit()
    conn.close()
    return redir("/friends", "You got a new friend! 🎉")


@app.post("/friends/decline/{uid}")
async def friend_decline(request: Request, uid: int):
    u, err = require_login(request)
    if err:
        return err
    conn = db()
    conn.execute("DELETE FROM friendships WHERE user_id=? AND friend_id=? AND status='pending'",
                 (uid, u["id"]))
    conn.commit()
    conn.close()
    return redir("/friends", "Request declined.")


@app.post("/friends/remove/{uid}")
async def friend_remove(request: Request, uid: int):
    u, err = require_login(request)
    if err:
        return err
    conn = db()
    conn.execute(
        "DELETE FROM friendships WHERE ((user_id=? AND friend_id=?) OR (user_id=? AND friend_id=?))",
        (u["id"], uid, uid, u["id"]))
    conn.commit()
    conn.close()
    return redir("/friends", "Removed from friends.")


# ---------------- search & explore ----------------
@app.get("/search", response_class=HTMLResponse)
def search(request: Request):
    u, err = require_login(request)
    if err:
        return err
    q = request.query_params.get("q", "").strip()[:80]
    job = request.query_params.get("job", "").strip()[:80]
    city = request.query_params.get("city", "").strip()[:80]
    results = []
    if q or job or city:
        conn = db()
        clauses, params = ["id != ?", "is_blocked=0"], [u["id"]]
        if q:
            clauses.append("(name LIKE ? OR hometown LIKE ? OR city LIKE ? OR workplace LIKE ? OR job_title LIKE ?)")
            params += [f"%{q}%"] * 5
        if job:
            clauses.append("(job_title LIKE ? OR workplace LIKE ?)")
            params += [f"%{job}%", f"%{job}%"]
        if city:
            clauses.append("(city LIKE ? OR hometown LIKE ?)")
            params += [f"%{city}%", f"%{city}%"]
        for r in conn.execute(
                f"SELECT id, name, avatar, verified, world_title, city, workplace, job_title "
                f"FROM users WHERE {' AND '.join(clauses)} "
                f"ORDER BY verified DESC, name ASC LIMIT 50", params):
            d = row_to_dict(r)
            if not is_blocked_either(u["id"], d["id"]):
                results.append(d)
        conn.close()
    return render(request, "search.html", {"q": q, "job": job, "city": city, "results": results})


@app.get("/explore", response_class=HTMLResponse)
def explore(request: Request):
    u, err = require_login(request)
    if err:
        return err
    conn = db()
    posts = []
    for p in conn.execute(
            "SELECT * FROM posts WHERE privacy='public' AND archived=0 "
            "ORDER BY created_at DESC LIMIT 100"):
        pd = row_to_dict(p)
        if can_view_post(u["id"], pd):
            posts.append(post_card_dict(pd, u["id"]))
    worlds = []
    for r in conn.execute(
            "SELECT id, name, avatar, verified, world_title, city FROM users "
            "WHERE id != ? AND is_blocked=0 ORDER BY verified DESC, created_at DESC LIMIT 24",
            (u["id"],)):
        d = row_to_dict(r)
        if not is_blocked_either(u["id"], d["id"]):
            worlds.append(d)
    conn.close()
    return render(request, "explore.html", {"posts": posts, "worlds": worlds})


# ---------------- inbox ----------------
@app.get("/inbox", response_class=HTMLResponse)
def inbox(request: Request):
    u, err = require_login(request)
    if err:
        return err
    conn = db()
    convos = []
    seen = set()
    for m in conn.execute(
            """SELECT * FROM messages
               WHERE sender_id=? OR recipient_id=? OR sender_id=0 AND recipient_id=?
               ORDER BY created_at DESC""", (u["id"], u["id"], u["id"])):
        other = m["recipient_id"] if m["sender_id"] == u["id"] else m["sender_id"]
        if other in seen:
            continue
        seen.add(other)
        if other == 0:
            o = {"id": 0, "name": "Post It Team", "avatar": "", "verified": 1}
        else:
            o = row_to_dict(conn.execute(
                "SELECT id, name, avatar, verified FROM users WHERE id=?", (other,)).fetchone())
            if not o or o.get("is_blocked"):
                continue
        if is_blocked_either(u["id"], other):
            continue
        unread = conn.execute(
            "SELECT COUNT(*) c FROM messages WHERE sender_id=? AND recipient_id=? AND read=0",
            (other, u["id"])).fetchone()["c"]
        convos.append({"other_id": other, "other_name": o["name"],
                       "other_avatar": o["avatar"], "verified": o["verified"],
                       "last_body": m["body"][:80], "last_at": fmt(m["created_at"]),
                       "unread": unread})
    conn.close()
    return render(request, "inbox.html", {"convos": convos})


@app.get("/inbox/{uid}", response_class=HTMLResponse)
def thread(request: Request, uid: int):
    u, err = require_login(request)
    if err:
        return err
    if uid != 0 and is_blocked_either(u["id"], uid):
        return redir("/inbox", "You can't message this person.")
    conn = db()
    if uid == 0:
        other = {"id": 0, "name": "Post It Team", "avatar": "", "verified": 1}
    else:
        o = conn.execute("SELECT id, name, avatar, verified FROM users WHERE id=?",
                         (uid,)).fetchone()
        if not o:
            conn.close()
            return redir("/inbox", "That person doesn't exist.")
        other = row_to_dict(o)
    msgs = []
    for m in conn.execute(
            """SELECT * FROM messages
               WHERE (sender_id=? AND recipient_id=?) OR (sender_id=? AND recipient_id=?)
               ORDER BY created_at ASC LIMIT 500""",
            (u["id"], uid, uid, u["id"])):
        d = row_to_dict(m)
        d["mine"] = (d["sender_id"] == u["id"])
        d["created_display"] = fmt(d["created_at"])
        msgs.append(d)
    conn.execute("UPDATE messages SET read=1 WHERE sender_id=? AND recipient_id=?",
                 (uid, u["id"]))
    conn.commit()
    conn.close()
    return render(request, "thread.html", {"other": other, "messages": msgs})


@app.post("/inbox/{uid}")
async def send_message(request: Request, uid: int):
    u, err = require_login(request)
    if err:
        return err
    form = await request.form()
    body = (form.get("body") or "").strip()[:2000]
    if uid != 0 and is_blocked_either(u["id"], uid):
        return redir("/inbox", "You can't message this person.")
    if not body:
        return redir(f"/inbox/{uid}")
    conn = db()
    conn.execute("INSERT INTO messages(sender_id, recipient_id, body, created_at) VALUES(?,?,?,?)",
                 (u["id"], uid, body, now_iso()))
    conn.commit()
    conn.close()
    return redir(f"/inbox/{uid}")


@app.post("/block/{uid}")
async def block_user(request: Request, uid: int):
    u, err = require_login(request)
    if err:
        return err
    conn = db()
    conn.execute("INSERT OR IGNORE INTO blocks(blocker_id, blocked_id, created_at) VALUES(?,?,?)",
                 (u["id"], uid, now_iso()))
    # drop any friendship
    conn.execute(
        "DELETE FROM friendships WHERE ((user_id=? AND friend_id=?) OR (user_id=? AND friend_id=?))",
        (u["id"], uid, uid, u["id"]))
    conn.commit()
    conn.close()
    return redir("/inbox", "Blocked. They can't see or message you anymore.")


@app.post("/unblock/{uid}")
async def unblock_user(request: Request, uid: int):
    u, err = require_login(request)
    if err:
        return err
    conn = db()
    conn.execute("DELETE FROM blocks WHERE blocker_id=? AND blocked_id=?", (u["id"], uid))
    conn.commit()
    conn.close()
    return redir("/inbox", "Unblocked.")


# ---------------- market ----------------
def _listing_dict(l, conn=None):
    import json as _json
    d = dict(l)
    try:
        d["photos"] = _json.loads(d["photos"] or "[]")
    except Exception:
        d["photos"] = []
    d["created_display"] = fmt(d["created_at"])
    return d


@app.get("/market", response_class=HTMLResponse)
def market(request: Request):
    u, err = require_login(request)
    if err:
        return err
    q = request.query_params.get("q", "").strip()[:80]
    cat = request.query_params.get("cat", "").strip()
    conn = db()
    clauses, params = ["users.is_blocked=0"], []
    if q:
        clauses.append("(title LIKE ? OR description LIKE ?)")
        params += [f"%{q}%", f"%{q}%"]
    if cat and cat in CATEGORIES:
        clauses.append("category=?")
        params.append(cat)
    listings = []
    for l in conn.execute(
            f"""SELECT market_listings.*, users.name AS seller_name, users.avatar AS seller_avatar,
                       users.verified AS seller_verified
                FROM market_listings JOIN users ON users.id=market_listings.user_id
                WHERE {' AND '.join(clauses)} ORDER BY created_at DESC LIMIT 100""", params):
        listings.append(_listing_dict(l))
    groups = [row_to_dict(g) for g in conn.execute(
        """SELECT market_groups.*, users.name AS owner_name,
                  (SELECT COUNT(*) FROM group_members WHERE group_id=market_groups.id) AS member_count
           FROM market_groups JOIN users ON users.id=market_groups.owner_id
           ORDER BY created_at DESC LIMIT 50""")]
    isos = []
    for i in conn.execute(
            """SELECT iso_posts.*, users.name AS user_name, users.avatar, users.verified
               FROM iso_posts JOIN users ON users.id=iso_posts.user_id
               WHERE users.is_blocked=0 ORDER BY created_at DESC LIMIT 50"""):
        d = row_to_dict(i)
        d["created_display"] = fmt(d["created_at"])
        isos.append(d)
    conn.close()
    return render(request, "market.html",
                  {"listings": listings, "groups": groups, "iso_posts": isos,
                   "categories": CATEGORIES, "q": q, "cat": cat})


@app.get("/market/new", response_class=HTMLResponse)
def listing_new_page(request: Request):
    u, err = require_login(request)
    if err:
        return err
    return render(request, "listing_form.html", {"categories": CATEGORIES})


@app.post("/market/new")
async def listing_new(request: Request):
    import json as _json
    u, err = require_login(request)
    if err:
        return err
    form = await request.form()
    title = (form.get("title") or "").strip()[:120]
    category = (form.get("category") or "Other").strip()
    if category not in CATEGORIES:
        category = "Other"
    try:
        price = float(form.get("price") or 0)
    except ValueError:
        price = 0
    description = (form.get("description") or "").strip()[:3000]
    shipping = 1 if form.get("shipping") else 0
    meetup_city = (form.get("meetup_city") or "").strip()[:120]
    if not title:
        return redir("/market/new", "Give your listing a title.")
    photos = []
    for f in form.getlist("photos"):
        url, kind = save_upload(f, "market")
        if url and kind == "photo":
            photos.append(url)
        if len(photos) >= 6:
            break
    conn = db()
    cur = conn.execute(
        """INSERT INTO market_listings(user_id, title, category, price, description,
                                       photos, shipping, meetup_city, created_at)
           VALUES(?,?,?,?,?,?,?,?,?)""",
        (u["id"], title, category, price, description, _json.dumps(photos),
         shipping, meetup_city, now_iso()))
    lid = cur.lastrowid
    conn.commit()
    conn.close()
    return redir(f"/market/{lid}", "Your listing is live! 🏷️")


@app.get("/market/{lid}", response_class=HTMLResponse)
def listing_detail(request: Request, lid: int):
    u, err = require_login(request)
    if err:
        return err
    conn = db()
    l = conn.execute(
        """SELECT market_listings.*, users.name AS seller_name, users.avatar AS seller_avatar,
                  users.verified AS seller_verified
           FROM market_listings JOIN users ON users.id=market_listings.user_id
           WHERE market_listings.id=?""", (lid,)).fetchone()
    if not l:
        conn.close()
        return redir("/market", "That listing is gone.")
    listing = _listing_dict(l)
    seller = {"id": l["user_id"], "name": l["seller_name"], "avatar": l["seller_avatar"],
              "verified": l["seller_verified"]}
    listing["seller"] = seller
    is_owner = (u["id"] == l["user_id"])
    offers = []
    if is_owner:
        for o in conn.execute(
                """SELECT offers.*, users.name AS buyer_name
                   FROM offers JOIN users ON users.id=offers.buyer_id
                   WHERE listing_id=? ORDER BY created_at DESC""", (lid,)):
            d = row_to_dict(o)
            d["created_display"] = fmt(d["created_at"])
            offers.append(d)
    rr = conn.execute("SELECT AVG(stars) a, COUNT(*) c FROM ratings WHERE seller_id=?",
                      (l["user_id"],)).fetchone()
    conn.close()
    return render(request, "listing.html",
                  {"listing": listing, "seller": seller, "is_owner": is_owner,
                   "offers": offers, "avg_rating": round(rr["a"] or 0, 1),
                   "rating_count": rr["c"]})


@app.post("/market/{lid}/offer")
async def make_offer(request: Request, lid: int):
    u, err = require_login(request)
    if err:
        return err
    form = await request.form()
    try:
        amount = float(form.get("amount") or 0)
    except ValueError:
        amount = 0
    message = (form.get("message") or "").strip()[:500]
    if amount <= 0:
        return redir(f"/market/{lid}", "Enter an offer amount.")
    conn = db()
    l = conn.execute("SELECT user_id FROM market_listings WHERE id=?", (lid,)).fetchone()
    if not l:
        conn.close()
        return redir("/market", "That listing is gone.")
    if l["user_id"] == u["id"]:
        conn.close()
        return redir(f"/market/{lid}", "That's your own listing!")
    conn.execute(
        "INSERT INTO offers(listing_id, buyer_id, amount, message, created_at) VALUES(?,?,?,?,?)",
        (lid, u["id"], amount, message, now_iso()))
    conn.commit()
    conn.close()
    return redir(f"/market/{lid}", "Offer sent to the seller! 💰")


@app.post("/market/{lid}/status")
async def listing_status(request: Request, lid: int):
    u, err = require_login(request)
    if err:
        return err
    form = await request.form()
    status = (form.get("status") or "").strip()
    if status not in ("active", "pending", "sold"):
        return redir(f"/market/{lid}")
    conn = db()
    conn.execute("UPDATE market_listings SET status=? WHERE id=? AND user_id=?",
                 (status, lid, u["id"]))
    conn.commit()
    conn.close()
    return redir(f"/market/{lid}", f"Marked as {status}.")


@app.post("/market/{lid}/delete")
async def listing_delete(request: Request, lid: int):
    u, err = require_login(request)
    if err:
        return err
    conn = db()
    l = conn.execute("SELECT * FROM market_listings WHERE id=? AND user_id=?",
                     (lid, u["id"])).fetchone()
    if l:
        import json as _json
        try:
            for ph in _json.loads(l["photos"] or "[]"):
                try:
                    os.remove(os.path.join(BASE, ph.lstrip("/")))
                except OSError:
                    pass
        except Exception:
            pass
        conn.execute("DELETE FROM offers WHERE listing_id=?", (lid,))
        conn.execute("DELETE FROM market_listings WHERE id=?", (lid,))
        conn.commit()
    conn.close()
    return redir("/market", "Listing removed.")


@app.post("/market/seller/{uid}/rate")
async def rate_seller(request: Request, uid: int):
    u, err = require_login(request)
    if err:
        return err
    form = await request.form()
    try:
        stars = int(form.get("stars") or 0)
    except ValueError:
        stars = 0
    comment = (form.get("comment") or "").strip()[:500]
    if stars < 1 or stars > 5 or uid == u["id"]:
        return redir("/market", "Pick 1–5 stars.")
    conn = db()
    conn.execute(
        """INSERT INTO ratings(seller_id, rater_id, stars, comment, created_at)
           VALUES(?,?,?,?,?)
           ON CONFLICT(seller_id, rater_id) DO UPDATE SET stars=excluded.stars,
               comment=excluded.comment, created_at=excluded.created_at""",
        (uid, u["id"], stars, comment, now_iso()))
    conn.commit()
    conn.close()
    return redir(f"/world/{uid}", "Rating saved! ⭐")


@app.get("/market/groups/new", response_class=HTMLResponse)
def group_new_page(request: Request):
    u, err = require_login(request)
    if err:
        return err
    return render(request, "group_form.html")


@app.post("/market/groups/new")
async def group_new(request: Request):
    u, err = require_login(request)
    if err:
        return err
    form = await request.form()
    name = (form.get("name") or "").strip()[:120]
    description = (form.get("description") or "").strip()[:1000]
    if not name:
        return redir("/market/groups/new", "Name your group.")
    conn = db()
    cur = conn.execute(
        "INSERT INTO market_groups(name, description, owner_id, created_at) VALUES(?,?,?,?)",
        (name, description, u["id"], now_iso()))
    gid = cur.lastrowid
    conn.execute("INSERT INTO group_members(group_id, user_id, created_at) VALUES(?,?,?)",
                 (gid, u["id"], now_iso()))
    conn.commit()
    conn.close()
    return redir(f"/market/groups/{gid}", "Group created! 🎉")


@app.get("/market/groups/{gid}", response_class=HTMLResponse)
def group_detail(request: Request, gid: int):
    u, err = require_login(request)
    if err:
        return err
    conn = db()
    g = conn.execute(
        """SELECT market_groups.*, users.name AS owner_name,
                  (SELECT COUNT(*) FROM group_members WHERE group_id=market_groups.id) AS member_count
           FROM market_groups JOIN users ON users.id=market_groups.owner_id
           WHERE market_groups.id=?""", (gid,)).fetchone()
    if not g:
        conn.close()
        return redir("/market", "That group is gone.")
    group = row_to_dict(g)
    is_member = bool(conn.execute(
        "SELECT 1 FROM group_members WHERE group_id=? AND user_id=?", (gid, u["id"])).fetchone())
    posts = []
    if is_member:
        for p in conn.execute(
                """SELECT group_posts.*, users.name AS user_name, users.avatar, users.verified
                   FROM group_posts JOIN users ON users.id=group_posts.user_id
                   WHERE group_id=? ORDER BY created_at DESC LIMIT 100""", (gid,)):
            d = row_to_dict(p)
            d["created_display"] = fmt(d["created_at"])
            posts.append(d)
    conn.close()
    return render(request, "group.html",
                  {"group": group, "is_member": is_member, "posts": posts})


@app.post("/market/groups/{gid}/join")
async def group_join(request: Request, gid: int):
    u, err = require_login(request)
    if err:
        return err
    conn = db()
    conn.execute("INSERT OR IGNORE INTO group_members(group_id, user_id, created_at) VALUES(?,?,?)",
                 (gid, u["id"], now_iso()))
    conn.commit()
    conn.close()
    return redir(f"/market/groups/{gid}", "You're in the group!")


@app.post("/market/groups/{gid}/post")
async def group_post(request: Request, gid: int):
    u, err = require_login(request)
    if err:
        return err
    form = await request.form()
    body = (form.get("body") or "").strip()[:2000]
    conn = db()
    member = conn.execute("SELECT 1 FROM group_members WHERE group_id=? AND user_id=?",
                          (gid, u["id"])).fetchone()
    if member and body:
        conn.execute("INSERT INTO group_posts(group_id, user_id, body, created_at) VALUES(?,?,?,?)",
                     (gid, u["id"], body, now_iso()))
        conn.commit()
    conn.close()
    return redir(f"/market/groups/{gid}")


@app.get("/market/iso/new", response_class=HTMLResponse)
def iso_new_page(request: Request):
    u, err = require_login(request)
    if err:
        return err
    return render(request, "iso_form.html", {"categories": CATEGORIES})


@app.post("/market/iso/new")
async def iso_new(request: Request):
    u, err = require_login(request)
    if err:
        return err
    form = await request.form()
    title = (form.get("title") or "").strip()[:120]
    description = (form.get("description") or "").strip()[:1000]
    category = (form.get("category") or "Other").strip()
    if category not in CATEGORIES:
        category = "Other"
    try:
        max_price = float(form.get("max_price") or 0)
    except ValueError:
        max_price = 0
    if not title:
        return redir("/market/iso/new", "Say what you're looking for.")
    conn = db()
    conn.execute(
        "INSERT INTO iso_posts(user_id, title, description, category, max_price, created_at) "
        "VALUES(?,?,?,?,?,?)", (u["id"], title, description, category, max_price, now_iso()))
    conn.commit()
    conn.close()
    return redir("/market", "ISO posted — good hunting! 🔍")


# ---------------- verified (coming soon; Stripe disabled by default) ----------------
@app.get("/verified", response_class=HTMLResponse)
def verified_page(request: Request):
    u, err = require_login(request)
    if err:
        return err
    return render(request, "verified.html", {"enabled": 1 if STRIPE_VERIFIED_ENABLED else 0})


@app.post("/verified/checkout")
async def verified_checkout(request: Request):
    u, err = require_login(request)
    if err:
        return JSONResponse({"ok": False, "error": "login"}, status_code=401)
    if not STRIPE_VERIFIED_ENABLED:
        # Prototype: subscriptions are not live. Flip STRIPE_VERIFIED_ENABLED=1
        # and set STRIPE_SECRET_KEY to enable real $5/mo checkout.
        return JSONResponse({"ok": False, "error": "coming soon"}, status_code=400)
    import stripe
    stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price_data": {
                "currency": "usd", "unit_amount": 500, "recurring": {"interval": "month"},
                "product_data": {"name": "Post It Verified"}} , "quantity": 1}],
            success_url=os.environ.get("POSTIT_URL", "http://127.0.0.1:8001") + "/verified?ok=1",
            cancel_url=os.environ.get("POSTIT_URL", "http://127.0.0.1:8001") + "/verified",
            metadata={"user_id": u["id"]})
        return JSONResponse({"ok": True, "url": session.url})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# ---------------- admin ----------------
def admin_required(request: Request):
    if not is_admin(request):
        return redir("/admin/login", "Admins only.")
    return None


@app.get("/admin/login", response_class=HTMLResponse)
def admin_login_page(request: Request):
    if is_admin(request):
        return redir("/admin")
    return templates.TemplateResponse(request, "admin/login.html",
                                      {"logo_url": "/static/logo.png", "flash": ""})


@app.post("/admin/login")
async def admin_login(request: Request):
    form = await request.form()
    password = form.get("password") or ""
    conn = db()
    row = conn.execute("SELECT value FROM settings WHERE key='admin_pw_hash'").fetchone()
    conn.close()
    ok = row and bcrypt.checkpw(password.encode(), row["value"].encode())
    if not ok:
        return templates.TemplateResponse(
            request, "admin/login.html",
            {"logo_url": "/static/logo.png", "flash": "Wrong password."})
    token = secrets.token_urlsafe(32)
    conn = db()
    conn.execute("INSERT INTO admin_sessions(token, created_at) VALUES(?,?)",
                 (token, now_iso()))
    conn.commit()
    conn.close()
    resp = redir("/admin")
    resp.set_cookie("postit_admin", token, httponly=True, max_age=12 * 3600, samesite="lax")
    return resp


@app.get("/admin/logout")
def admin_logout(request: Request):
    token = request.cookies.get("postit_admin", "")
    if token:
        conn = db()
        conn.execute("DELETE FROM admin_sessions WHERE token=?", (token,))
        conn.commit()
        conn.close()
    resp = redir("/admin/login")
    resp.delete_cookie("postit_admin")
    return resp


@app.get("/admin", response_class=HTMLResponse)
def admin_dash(request: Request):
    err = admin_required(request)
    if err:
        return err
    conn = db()
    stats = {
        "users": conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"],
        "posts": conn.execute("SELECT COUNT(*) c FROM posts").fetchone()["c"],
        "reports_open": conn.execute(
            "SELECT COUNT(*) c FROM reports WHERE status='open'").fetchone()["c"],
        "listings": conn.execute("SELECT COUNT(*) c FROM market_listings").fetchone()["c"],
    }
    recent = []
    for r in conn.execute(
            """SELECT reports.*, users.name AS reporter_name
               FROM reports JOIN users ON users.id=reports.reporter_id
               WHERE reports.status='open' ORDER BY created_at DESC LIMIT 10"""):
        d = row_to_dict(r)
        d["created_display"] = fmt(d["created_at"])
        recent.append(d)
    conn.close()
    return templates.TemplateResponse(request, "admin/dashboard.html",
                                      {"stats": stats, "recent_reports": recent,
                                       "logo_url": "/static/logo.png"})


@app.get("/admin/users", response_class=HTMLResponse)
def admin_users(request: Request):
    err = admin_required(request)
    if err:
        return err
    q = request.query_params.get("q", "").strip()[:80]
    conn = db()
    if q:
        rows = conn.execute(
            "SELECT * FROM users WHERE name LIKE ? OR email LIKE ? ORDER BY created_at DESC LIMIT 100",
            (f"%{q}%", f"%{q}%")).fetchall()
    else:
        rows = conn.execute("SELECT * FROM users ORDER BY created_at DESC LIMIT 100").fetchall()
    users = [row_to_dict(r) for r in rows]
    conn.close()
    return templates.TemplateResponse(request, "admin/users.html",
                                      {"users": users, "q": q, "logo_url": "/static/logo.png"})


@app.get("/admin/user/{uid}", response_class=HTMLResponse)
def admin_user_detail(request: Request, uid: int):
    err = admin_required(request)
    if err:
        return err
    profile = get_user(uid)
    if not profile:
        return redir("/admin/users", "No such user.")
    conn = db()
    posts = []
    for p in conn.execute("SELECT * FROM posts WHERE user_id=? ORDER BY created_at DESC LIMIT 50",
                          (uid,)):
        posts.append(post_card_dict(row_to_dict(p), uid))
    conn.close()
    return templates.TemplateResponse(request, "admin/user_detail.html",
                                      {"profile": profile, "posts": posts,
                                       "logo_url": "/static/logo.png"})


@app.post("/admin/user/{uid}/block")
async def admin_block_user(request: Request, uid: int):
    err = admin_required(request)
    if err:
        return err
    conn = db()
    conn.execute("UPDATE users SET is_blocked=1 WHERE id=?", (uid,))
    conn.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
    conn.commit()
    conn.close()
    return redir(f"/admin/user/{uid}", "Account blocked.")


@app.post("/admin/user/{uid}/unblock")
async def admin_unblock_user(request: Request, uid: int):
    err = admin_required(request)
    if err:
        return err
    conn = db()
    conn.execute("UPDATE users SET is_blocked=0 WHERE id=?", (uid,))
    conn.commit()
    conn.close()
    return redir(f"/admin/user/{uid}", "Account unblocked.")


@app.post("/admin/user/{uid}/delete")
async def admin_delete_user(request: Request, uid: int):
    err = admin_required(request)
    if err:
        return err
    conn = db()
    # collect this user's files first so we only delete theirs
    user_files = []
    ur = conn.execute("SELECT avatar, cover FROM users WHERE id=?", (uid,)).fetchone()
    if ur:
        user_files += [ur["avatar"], ur["cover"]]
    for pr in conn.execute("SELECT media FROM posts WHERE user_id=?", (uid,)):
        if pr["media"]:
            user_files.append(pr["media"])
    for sr in conn.execute("SELECT media FROM stories WHERE user_id=?", (uid,)):
        user_files.append(sr["media"])
    import json as _json
    for lr in conn.execute("SELECT photos FROM market_listings WHERE user_id=?", (uid,)):
        try:
            user_files += _json.loads(lr["photos"] or "[]")
        except Exception:
            pass
    pids = [r["id"] for r in conn.execute("SELECT id FROM posts WHERE user_id=?", (uid,))]
    for pid in pids:
        conn.execute("DELETE FROM reactions WHERE post_id=?", (pid,))
        conn.execute("DELETE FROM comments WHERE post_id=?", (pid,))
    conn.execute("DELETE FROM posts WHERE user_id=?", (uid,))
    conn.execute("DELETE FROM comments WHERE user_id=?", (uid,))
    conn.execute("DELETE FROM reactions WHERE user_id=?", (uid,))
    conn.execute("DELETE FROM stories WHERE user_id=?", (uid,))
    conn.execute("DELETE FROM messages WHERE sender_id=? OR recipient_id=?", (uid, uid))
    conn.execute("DELETE FROM friendships WHERE user_id=? OR friend_id=?", (uid, uid))
    conn.execute("DELETE FROM blocks WHERE blocker_id=? OR blocked_id=?", (uid, uid))
    conn.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
    conn.execute("DELETE FROM offers WHERE buyer_id=?", (uid,))
    conn.execute("DELETE FROM market_listings WHERE user_id=?", (uid,))
    conn.execute("DELETE FROM ratings WHERE seller_id=? OR rater_id=?", (uid, uid))
    conn.execute("DELETE FROM iso_posts WHERE user_id=?", (uid,))
    conn.execute("DELETE FROM group_posts WHERE user_id=?", (uid,))
    conn.execute("DELETE FROM group_members WHERE user_id=?", (uid,))
    conn.execute("DELETE FROM reports WHERE reporter_id=?", (uid,))
    conn.execute("DELETE FROM users WHERE id=?", (uid,))
    conn.commit()
    conn.close()
    for uf in user_files:
        if uf:
            try:
                os.remove(os.path.join(BASE, uf.lstrip("/")))
            except OSError:
                pass
    return redir("/admin/users", "Account deleted.")


@app.post("/admin/user/{uid}/message")
async def admin_message_user(request: Request, uid: int):
    err = admin_required(request)
    if err:
        return err
    form = await request.form()
    body = (form.get("body") or "").strip()[:2000]
    if body and get_user(uid):
        conn = db()
        conn.execute(
            "INSERT INTO messages(sender_id, recipient_id, body, created_at) VALUES(0,?,?,?)",
            (uid, f"[Post It Team] {body}", now_iso()))
        conn.commit()
        conn.close()
    return redir(f"/admin/user/{uid}", "Message sent.")


@app.get("/admin/reports", response_class=HTMLResponse)
def admin_reports(request: Request):
    err = admin_required(request)
    if err:
        return err
    conn = db()
    reports = []
    for r in conn.execute(
            """SELECT reports.*, users.name AS reporter_name
               FROM reports JOIN users ON users.id=reports.reporter_id
               ORDER BY CASE status WHEN 'open' THEN 0 ELSE 1 END, created_at DESC LIMIT 200"""):
        d = row_to_dict(r)
        d["created_display"] = fmt(d["created_at"])
        if d["target_type"] == "post":
            p = conn.execute("SELECT body, user_id FROM posts WHERE id=?",
                             (d["target_id"],)).fetchone()
            d["target_summary"] = ("Post: " + (p["body"][:100] if p else "(deleted)"))
        else:
            t = conn.execute("SELECT name FROM users WHERE id=?", (d["target_id"],)).fetchone()
            d["target_summary"] = "User: " + (t["name"] if t else "(deleted)")
        reports.append(d)
    conn.close()
    return templates.TemplateResponse(request, "admin/reports.html",
                                      {"reports": reports, "logo_url": "/static/logo.png"})


@app.post("/admin/reports/{rid}/resolve")
async def admin_resolve_report(request: Request, rid: int):
    err = admin_required(request)
    if err:
        return err
    conn = db()
    conn.execute("UPDATE reports SET status='resolved' WHERE id=?", (rid,))
    conn.commit()
    conn.close()
    return redir("/admin/reports", "Report resolved.")


@app.get("/admin/posts", response_class=HTMLResponse)
def admin_posts(request: Request):
    err = admin_required(request)
    if err:
        return err
    conn = db()
    posts = []
    for p in conn.execute(
            """SELECT posts.*, users.name AS author_name
               FROM posts JOIN users ON users.id=posts.user_id
               ORDER BY created_at DESC LIMIT 200"""):
        d = row_to_dict(p)
        d["created_display"] = fmt(d["created_at"])
        posts.append(d)
    conn.close()
    return templates.TemplateResponse(request, "admin/posts.html",
                                      {"posts": posts, "logo_url": "/static/logo.png"})


@app.post("/admin/post/{pid}/delete")
async def admin_delete_post(request: Request, pid: int):
    err = admin_required(request)
    if err:
        return err
    conn = db()
    conn.execute("DELETE FROM reactions WHERE post_id=?", (pid,))
    conn.execute("DELETE FROM comments WHERE post_id=?", (pid,))
    conn.execute("DELETE FROM posts WHERE id=?", (pid,))
    conn.commit()
    conn.close()
    return redir("/admin/posts", "Post deleted.")
