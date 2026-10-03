#!/usr/bin/env python3
"""
DateSwipe — Tinder-style swipe dating web app.
Backend: Python stdlib only (http.server, sqlite3, hashlib, hmac, secrets).
Run:  python3 app.py   ->   http://127.0.0.1:8767
"""
import base64
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import time
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, unquote, parse_qs

# ---------------------------------------------------------------- paths/config
ROOT = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(ROOT, "web")
UPLOADS = os.path.join(ROOT, "uploads")
DB_PATH = os.path.join(ROOT, "date_swipe.db")
CONFIG_PATH = os.path.join(ROOT, "config.json")
PORT = int(os.environ.get("PORT", 8767))

FREE_LIKES_PER_DAY = 20
MAX_PHOTOS = 6
MAX_PHOTO_BYTES = 5 * 1024 * 1024
ALLOWED_PHOTO_EXT = {".jpg", ".jpeg", ".png", ".webp"}
SESSION_COOKIE = "ds_session"
SESSION_MAX_AGE = 30 * 24 * 3600
REFERRAL_REWARD_DAYS = 7  # premium days a referrer earns per successful adult referral
SIGNAL_TTL = 300  # call-signaling rows expire after 5 minutes
CALL_KINDS = {"ring", "offer", "answer", "ice", "hangup"}
REFERRAL_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I/L
GAMES = ("tictactoe", "rps")
RPS_WIN_SCORE = 3  # first to 3 rounds wins
# Paid gift catalog: id -> (emoji, name, price in coins)
GIFTS = [
    {"id": "rose", "emoji": "🌹", "name": "Rose", "price": 10},
    {"id": "choco", "emoji": "🍫", "name": "Chocolates", "price": 30},
    {"id": "teddy", "emoji": "🧸", "name": "Teddy Bear", "price": 50},
    {"id": "perfume", "emoji": "🌸", "name": "Perfume", "price": 100},
    {"id": "watch", "emoji": "⌚", "name": "Watch", "price": 250},
    {"id": "ring", "emoji": "💍", "name": "Diamond Ring", "price": 500},
    {"id": "crown", "emoji": "👑", "name": "Crown", "price": 1000},
    {"id": "rocket", "emoji": "🚀", "name": "Rocket", "price": 2000},
]
GIFT_BY_ID = {g["id"]: g for g in GIFTS}


def load_config():
    """Load config.json; generate secrets on first run."""
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
    else:
        cfg = {}
    changed = False
    if not cfg.get("secret"):
        cfg["secret"] = secrets.token_hex(32)
        changed = True
    if not cfg.get("admin_token"):
        cfg["admin_token"] = secrets.token_hex(16)
        changed = True
    if "stripe_payment_link" not in cfg:
        cfg["stripe_payment_link"] = ""
        changed = True
    if "ads" not in cfg:
        # Ad monetization (e.g. Google AdSense). Fill client_id + slot ids after
        # AdSense approval; frontend only renders units when enabled is true.
        cfg["ads"] = {"enabled": False, "client_id": "",
                      "slots": {"discover": "", "matches": "", "chat": ""}}
        changed = True
    if changed:
        with open(CONFIG_PATH, "w") as f:
            json.dump(cfg, f, indent=2)
    return cfg


CONFIG = load_config()
SECRET = CONFIG["secret"].encode()

# ---------------------------------------------------------------- database
db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.row_factory = sqlite3.Row


def init_db():
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            pw_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            name TEXT NOT NULL,
            birthdate TEXT NOT NULL,
            gender TEXT NOT NULL,
            looking_for TEXT NOT NULL,
            bio TEXT DEFAULT '',
            interests TEXT DEFAULT '',
            photos TEXT DEFAULT '[]',
            created_ts INTEGER NOT NULL,
            is_premium INTEGER DEFAULT 0,
            premium_until INTEGER DEFAULT 0,
            banned INTEGER DEFAULT 0,
            referral_code TEXT DEFAULT '',
            discoverable INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS swipes(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            swiper_id INTEGER NOT NULL,
            target_id INTEGER NOT NULL,
            liked INTEGER NOT NULL,
            ts INTEGER NOT NULL,
            UNIQUE(swiper_id, target_id)
        );
        CREATE TABLE IF NOT EXISTS matches(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_a INTEGER NOT NULL,
            user_b INTEGER NOT NULL,
            ts INTEGER NOT NULL,
            UNIQUE(user_a, user_b)
        );
        CREATE TABLE IF NOT EXISTS messages(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id INTEGER NOT NULL,
            sender_id INTEGER NOT NULL,
            text TEXT NOT NULL,
            ts INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reports(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reporter_id INTEGER NOT NULL,
            target_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            ts INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS blocks(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            blocker_id INTEGER NOT NULL,
            blocked_id INTEGER NOT NULL,
            UNIQUE(blocker_id, blocked_id)
        );
        CREATE TABLE IF NOT EXISTS signals(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id INTEGER NOT NULL,
            sender_id INTEGER NOT NULL,
            kind TEXT NOT NULL,
            payload TEXT DEFAULT '',
            ts INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS referrals(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            referrer_id INTEGER NOT NULL,
            referred_id INTEGER NOT NULL UNIQUE,
            ts INTEGER NOT NULL,
            rewarded INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS game_sessions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id INTEGER NOT NULL,
            game TEXT NOT NULL,
            player_a INTEGER NOT NULL,
            player_b INTEGER NOT NULL,
            state TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            winner_id INTEGER,
            ts INTEGER NOT NULL,
            updated_ts INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS wallets(
            user_id INTEGER PRIMARY KEY,
            coins INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_swipes_swiper ON swipes(swiper_id);
        CREATE INDEX IF NOT EXISTS idx_swipes_target ON swipes(target_id);
        CREATE INDEX IF NOT EXISTS idx_matches_users ON matches(user_a, user_b);
        CREATE INDEX IF NOT EXISTS idx_messages_match ON messages(match_id);
        CREATE INDEX IF NOT EXISTS idx_signals_match ON signals(match_id);
        """
    )
    db.commit()
    # --- migration: referral_code column on users (fresh DBs already have it
    # via CREATE TABLE below only if we add it there; keep ALTER for upgrades)
    try:
        db.execute("ALTER TABLE users ADD COLUMN referral_code TEXT")
        db.commit()
    except sqlite3.OperationalError:
        pass
    try:
        db.execute("ALTER TABLE users ADD COLUMN discoverable INTEGER DEFAULT 1")
        db.commit()
    except sqlite3.OperationalError:
        pass
    # --- messages: kind/extra for game invites + gifts -------------------
    for ddl in ("ALTER TABLE messages ADD COLUMN kind TEXT DEFAULT 'text'",
                "ALTER TABLE messages ADD COLUMN extra TEXT DEFAULT '{}'"):
        try:
            db.execute(ddl)
            db.commit()
        except sqlite3.OperationalError:
            pass
    # backfill referral codes for any users missing one
    for row in db.execute(
            "SELECT id FROM users WHERE referral_code IS NULL OR referral_code=''"):
        db.execute("UPDATE users SET referral_code=? WHERE id=?",
                   (gen_referral_code(), row["id"]))
    db.commit()


init_db()

# ---------------------------------------------------------------- helpers
def now():
    return int(time.time())


def calc_age(birthdate):
    """birthdate 'YYYY-MM-DD' -> age in years, or None if invalid."""
    try:
        y, m, d = (int(x) for x in birthdate.split("-"))
        born = date(y, m, d)
    except Exception:
        return None
    today = date.today()
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def adult_cutoff():
    """Latest birthdate string that is still 18+ today."""
    t = date.today()
    try:
        cutoff = t.replace(year=t.year - 18)
    except ValueError:  # Feb 29 edge
        cutoff = t.replace(year=t.year - 18, day=28)
    return cutoff.isoformat()


def new_salt():
    return secrets.token_hex(16)


def hash_pw(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000).hex()


def make_token(user_id):
    rand = secrets.token_hex(16)
    body = f"{user_id}.{rand}"
    sig = hmac.new(SECRET, body.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{body}.{sig}"


def verify_token(token):
    try:
        uid_s, rand, sig = token.split(".")
        body = f"{uid_s}.{rand}"
        expect = hmac.new(SECRET, body.encode(), hashlib.sha256).hexdigest()[:32]
        if hmac.compare_digest(expect, sig):
            return int(uid_s)
    except Exception:
        pass
    return None


def public_user(row, include_private=False):
    """Serialize a user row for API output (never includes pw_hash/salt)."""
    photos = []
    try:
        photos = json.loads(row["photos"] or "[]")
    except Exception:
        pass
    out = {
        "id": row["id"],
        "name": row["name"],
        "age": calc_age(row["birthdate"]),
        "gender": row["gender"],
        "looking_for": row["looking_for"],
        "bio": row["bio"] or "",
        "interests": row["interests"] or "",
        "photos": ["/uploads/" + p for p in photos],
        "is_premium": bool(row["is_premium"] and row["premium_until"] > now()),
    }
    if include_private:
        out["referral_code"] = row["referral_code"] or ""
        out["email"] = row["email"]
        try:
            out["discoverable"] = bool(row["discoverable"])
        except (KeyError, IndexError):
            out["discoverable"] = True
    return out


def gen_referral_code():
    """8-char unique referral code."""
    for _ in range(50):
        code = "".join(secrets.choice(REFERRAL_ALPHABET) for _ in range(8))
        if not db.execute("SELECT id FROM users WHERE referral_code=?",
                          (code,)).fetchone():
            return code
    return secrets.token_hex(4).upper()


def grant_referral_reward(referrer_id):
    """+REFERRAL_REWARD_DAYS premium for the referrer."""
    row = db.execute("SELECT * FROM users WHERE id=?", (referrer_id,)).fetchone()
    if not row:
        return
    until = max(now(), row["premium_until"]) + REFERRAL_REWARD_DAYS * 86400
    db.execute("UPDATE users SET is_premium=1, premium_until=? WHERE id=?",
               (until, referrer_id))
    db.commit()


def get_wallet(user_id):
    """Return coin balance, auto-creating the wallet row."""
    row = db.execute("SELECT coins FROM wallets WHERE user_id=?", (user_id,)).fetchone()
    if not row:
        db.execute("INSERT INTO wallets(user_id,coins) VALUES(?,0)", (user_id,))
        db.commit()
        return 0
    return row["coins"]


def add_coins(user_id, delta):
    get_wallet(user_id)
    db.execute("UPDATE wallets SET coins = coins + ? WHERE user_id=?", (delta, user_id))
    db.commit()
    return get_wallet(user_id)


# ---------------------------------------------------------------- games
TTT_LINES = ((0, 1, 2), (3, 4, 5), (6, 7, 8),
             (0, 3, 6), (1, 4, 7), (2, 5, 8),
             (0, 4, 8), (2, 4, 6))
RPS_BEATS = {"rock": "scissors", "scissors": "paper", "paper": "rock"}


def ttt_winner(board):
    for a, b, c in TTT_LINES:
        if board[a] and board[a] == board[b] == board[c]:
            return board[a]
    return None


def new_game_state(game, player_a):
    if game == "tictactoe":
        return {"board": [None] * 9, "turn": player_a}
    return {"choices": {}, "round": 1, "score": {"a": 0, "b": 0}}


def is_premium(row):
    return bool(row["is_premium"] and row["premium_until"] > now())

# ---------------------------------------------------------------- HTTP layer
class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass  # quiet

    # -- response helpers ------------------------------------------------
    def send_json(self, obj, code=200, extra_headers=None):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path, ctype=None):
        if not os.path.isfile(path):
            self.send_error(404)
            return
        ctype = ctype or mimetypes.guess_type(path)[0] or "application/octet-stream"
        # never serve .db / .json config as static
        if path.endswith((".db", ".db-journal")) or os.path.basename(path) == "config.json":
            self.send_error(403)
            return
        size = os.path.getsize(path)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(size))
        self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()
        with open(path, "rb") as f:
            while True:
                chunk = f.read(256 * 1024)
                if not chunk:
                    break
                self.wfile.write(chunk)

    def read_body(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        return self.rfile.read(n) if n else b""

    def read_json(self):
        try:
            return json.loads(self.read_body().decode() or "{}")
        except Exception:
            return None

    def get_cookie(self, name):
        raw = self.headers.get("Cookie", "")
        for part in raw.split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                if k == name:
                    return v
        return None

    def current_user(self):
        tok = self.get_cookie(SESSION_COOKIE)
        uid = verify_token(tok) if tok else None
        if not uid:
            return None
        row = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if not row or row["banned"]:
            return None
        return row

    def require_user(self):
        u = self.current_user()
        if not u:
            self.send_json({"error": "login required"}, 401)
        return u

    # -- multipart parser (for photo upload) -----------------------------
    @staticmethod
    def parse_multipart(body, boundary):
        """Return list of (headers dict, data bytes)."""
        parts = []
        for seg in body.split(b"--" + boundary)[1:]:
            seg = seg.strip(b"\r\n")
            if not seg or seg == b"--":
                continue
            if seg.endswith(b"--"):
                seg = seg[:-2].rstrip(b"\r\n")
            idx = seg.find(b"\r\n\r\n")
            if idx < 0:
                continue
            raw_headers = seg[:idx].decode("latin-1")
            data = seg[idx + 4:]
            if data.endswith(b"\r\n"):
                data = data[:-2]
            headers = {}
            for line in raw_headers.split("\r\n"):
                if ":" in line:
                    k, v = line.split(":", 1)
                    headers[k.strip().lower()] = v.strip()
            parts.append((headers, data))
        return parts

    # ================================================================ GET ==
    def do_GET(self):
        pu = urlparse(self.path)
        path, qs = pu.path, parse_qs(pu.query)

        if path == "/api/me":
            u = self.require_user()
            if u:
                self.send_json({"ok": True, "user": public_user(u, include_private=True)})
            return
        if path == "/api/discover":
            u = self.require_user()
            if u:
                self.send_json({"ok": True, "profiles": self.discover(u)})
            return
        if path == "/api/liked_by":
            u = self.require_user()
            if not u:
                return
            if not is_premium(u):
                self.send_json({"error": "premium only", "upgrade": True}, 403)
                return
            self.send_json({"ok": True, "profiles": self.liked_by(u)})
            return
        if path == "/api/matches":
            u = self.require_user()
            if u:
                self.send_json({"ok": True, "matches": self.match_list(u)})
            return
        if path == "/api/messages":
            u = self.require_user()
            if not u:
                return
            try:
                mid = int(qs.get("match_id", ["0"])[0])
            except ValueError:
                mid = 0
            m = db.execute(
                "SELECT * FROM matches WHERE id=? AND (user_a=? OR user_b=?)",
                (mid, u["id"], u["id"]),
            ).fetchone()
            if not m:
                self.send_json({"error": "no such match"}, 404)
                return
            rows = db.execute(
                "SELECT id, sender_id, text, ts, kind, extra FROM messages WHERE match_id=? ORDER BY ts ASC",
                (mid,),
            ).fetchall()
            self.send_json({"ok": True, "messages": [dict(r) for r in rows]})
            return
        if path == "/api/premium/status":
            u = self.require_user()
            if u:
                self.send_json({"ok": True, "is_premium": is_premium(u),
                                "premium_until": u["premium_until"]})
            return
        if path == "/api/paylink":
            # public: just reveals whether a payment link is configured
            self.send_json({"ok": True,
                            "link": CONFIG.get("stripe_payment_link") or ""})
            return
        if path == "/api/ads/config":
            # public: reveals ad setup only (safe — same visibility as AdSense snippet)
            a = CONFIG.get("ads") or {}
            on = bool(a.get("enabled") and a.get("client_id"))
            self.send_json({"ok": True, "enabled": on,
                            "client_id": a.get("client_id") if on else "",
                            "slots": a.get("slots") if on else {}})
            return
        if path == "/api/referrals":
            u = self.require_user()
            if not u:
                return
            count = db.execute(
                "SELECT COUNT(*) c FROM referrals WHERE referrer_id=?",
                (u["id"],)).fetchone()["c"]
            host = self.headers.get("Host", f"127.0.0.1:{PORT}")
            code = u["referral_code"] or ""
            self.send_json({
                "ok": True,
                "code": code,
                "invite_link": f"http://{host}/?ref={code}",
                "referrals_count": count,
                "premium_days_earned": count * REFERRAL_REWARD_DAYS,
            })
            return
        if path == "/api/admin/referrals":
            token = qs.get("admin_token", [""])[0]
            if not hmac.compare_digest(token, CONFIG.get("admin_token") or ""):
                return self.send_json({"error": "forbidden"}, 403)
            rows = db.execute(
                """SELECT r.id, r.code, r.ts, r.rewarded,
                          ref.email AS referrer_email, got.email AS referred_email
                   FROM referrals r
                   JOIN users ref ON ref.id = r.referrer_id
                   JOIN users got ON got.id = r.referred_id
                   ORDER BY r.ts DESC""").fetchall()
            self.send_json({"ok": True, "referrals": [dict(r) for r in rows]})
            return
        if path == "/api/call/signal":
            u = self.require_user()
            if not u:
                return
            try:
                mid = int(qs.get("match_id", ["0"])[0])
                since = int(qs.get("since", ["0"])[0])
            except ValueError:
                mid, since = 0, 0
            m = db.execute(
                "SELECT * FROM matches WHERE id=? AND (user_a=? OR user_b=?)",
                (mid, u["id"], u["id"])).fetchone()
            if not m:
                return self.send_json({"error": "no such match"}, 404)
            # expire old signaling rows on every read
            db.execute("DELETE FROM signals WHERE ts < ?", (now() - SIGNAL_TTL,))
            db.commit()
            rows = db.execute(
                "SELECT id, sender_id, kind, payload, ts FROM signals"
                " WHERE match_id=? AND id>? ORDER BY id ASC",
                (mid, since)).fetchall()
            self.send_json({"ok": True, "signals": [dict(r) for r in rows]})
            return
        if path == "/api/gifts":
            self.send_json({"ok": True, "gifts": GIFTS})
            return
        if path == "/api/wallet":
            u = self.require_user()
            if u:
                self.send_json({"ok": True, "coins": get_wallet(u["id"])})
            return
        if path == "/api/game/pending":
            u = self.require_user()
            if not u:
                return
            try:
                mid = int(qs.get("match_id", ["0"])[0])
            except ValueError:
                mid = 0
            if not self.match_of(u, mid):
                return self.send_json({"error": "no such match"}, 404)
            rows = db.execute(
                "SELECT id, game, player_a, player_b, status, winner_id, updated_ts"
                " FROM game_sessions WHERE match_id=? AND status != 'finished'"
                " ORDER BY updated_ts DESC",
                (mid,)).fetchall()
            self.send_json({"ok": True, "sessions": [dict(r) for r in rows]})
            return
        if path == "/api/game/state":
            u = self.require_user()
            if not u:
                return
            try:
                sid = int(qs.get("session_id", ["0"])[0])
            except ValueError:
                sid = 0
            gs = self.game_session_for(u, sid)
            if not gs:
                return self.send_json({"error": "no such game"}, 403)
            self.send_json({"ok": True, "session": self.public_session(gs, u["id"])})
            return
        if path == "/manifest.json":
            return self.send_file(os.path.join(WEB, "manifest.json"), "application/manifest+json")
        if path == "/sw.js":
            return self.send_file(os.path.join(WEB, "sw.js"), "application/javascript")
        if path.startswith("/uploads/"):
            name = os.path.basename(unquote(path[len("/uploads/"):]))
            if not re.fullmatch(r"[A-Za-z0-9._-]+", name):
                return self.send_error(400)
            return self.send_file(os.path.join(UPLOADS, name))
        # static frontend
        if path == "/" or path == "":
            return self.send_file(os.path.join(WEB, "index.html"), "text/html; charset=utf-8")
        rel = unquote(path.lstrip("/"))
        if ".." in rel or rel.startswith("/"):
            return self.send_error(400)
        fpath = os.path.join(WEB, rel)
        if os.path.isfile(fpath):
            return self.send_file(fpath)
        return self.send_error(404)

    # ------------------------------------------------------- discovery ----
    def discover(self, u):
        cutoff = adult_cutoff()
        rows = db.execute(
            """SELECT * FROM users u WHERE u.id != ?
               AND u.banned = 0
               AND u.discoverable != 0
               AND u.birthdate <= ?
               AND u.id NOT IN (SELECT target_id FROM swipes WHERE swiper_id = ?)
               AND u.id NOT IN (SELECT blocker_id FROM blocks WHERE blocked_id = ?)
               AND u.id NOT IN (SELECT blocked_id FROM blocks WHERE blocker_id = ?)
               AND (? = 'everyone' OR u.gender = ?)
               AND (u.looking_for = 'everyone' OR u.looking_for = ?)
               ORDER BY u.created_ts DESC LIMIT 20""",
            (u["id"], cutoff, u["id"], u["id"], u["id"],
             u["looking_for"], u["looking_for"], u["gender"]),
        ).fetchall()
        return [public_user(r) for r in rows]

    def liked_by(self, u):
        rows = db.execute(
            """SELECT u.* FROM swipes s JOIN users u ON u.id = s.swiper_id
               WHERE s.target_id = ? AND s.liked = 1 AND u.banned = 0
               AND s.swiper_id NOT IN (SELECT target_id FROM swipes WHERE swiper_id = ?)
               AND s.swiper_id NOT IN (SELECT blocker_id FROM blocks WHERE blocked_id = ?)
               AND s.swiper_id NOT IN (SELECT blocked_id FROM blocks WHERE blocker_id = ?)
               ORDER BY s.ts DESC LIMIT 50""",
            (u["id"], u["id"], u["id"], u["id"]),
        ).fetchall()
        return [public_user(r) for r in rows]

    def match_list(self, u):
        rows = db.execute(
            """SELECT * FROM matches WHERE user_a=? OR user_b=? ORDER BY ts DESC""",
            (u["id"], u["id"]),
        ).fetchall()
        out = []
        for m in rows:
            other_id = m["user_b"] if m["user_a"] == u["id"] else m["user_a"]
            other = db.execute("SELECT * FROM users WHERE id=?", (other_id,)).fetchone()
            if not other:
                continue
            last = db.execute(
                "SELECT text, ts, sender_id FROM messages WHERE match_id=? ORDER BY ts DESC LIMIT 1",
                (m["id"],),
            ).fetchone()
            ou = public_user(other)
            out.append({
                "match_id": m["id"],
                "user": {"id": ou["id"], "name": ou["name"], "age": ou["age"],
                         "photos": ou["photos"]},
                "last_message": dict(last) if last else None,
                "ts": m["ts"],
            })
        return out

    def match_of(self, u, mid):
        return db.execute(
            "SELECT * FROM matches WHERE id=? AND (user_a=? OR user_b=?)",
            (mid, u["id"], u["id"])).fetchone()

    def game_session_for(self, u, sid):
        return db.execute(
            "SELECT * FROM game_sessions WHERE id=? AND (player_a=? OR player_b=?)",
            (sid, u["id"], u["id"])).fetchone()

    @staticmethod
    def public_session(gs, uid):
        return {
            "session_id": gs["id"],
            "match_id": gs["match_id"],
            "game": gs["game"],
            "player_a": gs["player_a"],
            "player_b": gs["player_b"],
            "you_are": "a" if gs["player_a"] == uid else "b",
            "state": json.loads(gs["state"]),
            "status": gs["status"],
            "winner_id": gs["winner_id"],
            "updated_ts": gs["updated_ts"],
        }

    # =============================================================== POST ==
    def do_POST(self):
        pu = urlparse(self.path)
        path = pu.path

        if path == "/api/signup":
            return self.api_signup()
        if path == "/api/login":
            return self.api_login()
        if path == "/api/logout":
            self.send_response(200)
            self.send_header("Set-Cookie",
                             f"{SESSION_COOKIE}=; HttpOnly; Path=/; SameSite=Lax; Max-Age=0")
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok": true}')
            return
        if path == "/api/profile":
            u = self.require_user()
            if u:
                self.api_profile(u)
            return
        if path == "/api/upload":
            u = self.require_user()
            if u:
                self.api_upload(u)
            return
        if path == "/api/swipe":
            u = self.require_user()
            if u:
                self.api_swipe(u)
            return
        if path == "/api/message":
            u = self.require_user()
            if u:
                self.api_message(u)
            return
        if path == "/api/report":
            u = self.require_user()
            if u:
                self.api_report(u)
            return
        if path == "/api/block":
            u = self.require_user()
            if u:
                self.api_block(u)
            return
        if path == "/api/admin/grant_premium":
            return self.api_grant_premium()
        if path == "/api/call/signal":
            u = self.require_user()
            if u:
                self.api_call_signal(u)
            return
        if path == "/api/game/start":
            u = self.require_user()
            if u:
                self.api_game_start(u)
            return
        if path == "/api/game/move":
            u = self.require_user()
            if u:
                self.api_game_move(u)
            return
        if path == "/api/gift/send":
            u = self.require_user()
            if u:
                self.api_gift_send(u)
            return
        if path == "/api/admin/grant_coins":
            return self.api_grant_coins()
        return self.send_error(404)

    # ---------------------------------------------------------- auth ------
    def api_signup(self):
        d = self.read_json()
        if d is None:
            return self.send_json({"error": "bad json"}, 400)
        email = (d.get("email") or "").strip().lower()
        password = d.get("password") or ""
        name = (d.get("name") or "").strip()
        birthdate = (d.get("birthdate") or "").strip()
        gender = (d.get("gender") or "").strip()
        looking_for = (d.get("looking_for") or "").strip()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            return self.send_json({"error": "invalid email"}, 400)
        if len(password) < 6:
            return self.send_json({"error": "password must be at least 6 characters"}, 400)
        if not name:
            return self.send_json({"error": "name required"}, 400)
        if gender not in ("male", "female"):
            return self.send_json({"error": "gender must be male or female"}, 400)
        if looking_for not in ("male", "female", "everyone"):
            return self.send_json({"error": "looking_for must be male/female/everyone"}, 400)
        age = calc_age(birthdate)
        if age is None:
            return self.send_json({"error": "invalid birthdate (use YYYY-MM-DD)"}, 400)
        if age < 18:
            return self.send_json({"error": "you must be 18 or older"}, 403)
        if db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone():
            return self.send_json({"error": "email already registered"}, 409)
        salt = new_salt()
        my_code = gen_referral_code()
        cur = db.execute(
            """INSERT INTO users(email,pw_hash,salt,name,birthdate,gender,looking_for,
                                 created_ts,referral_code)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (email, hash_pw(password, salt), salt, name, birthdate, gender,
             looking_for, now(), my_code),
        )
        db.commit()
        uid = cur.lastrowid
        # --- optional referral: reward the referrer with +7 days premium ----
        ref_code = (d.get("referral_code") or "").strip().upper()
        if ref_code:
            ref = db.execute("SELECT * FROM users WHERE referral_code=? AND banned=0",
                             (ref_code,)).fetchone()
            if not ref:
                db.execute("DELETE FROM users WHERE id=?", (uid,))
                db.commit()
                return self.send_json({"error": "invalid referral code"}, 400)
            if ref["id"] == uid:
                db.execute("DELETE FROM users WHERE id=?", (uid,))
                db.commit()
                return self.send_json({"error": "cannot refer yourself"}, 400)
            try:
                db.execute(
                    "INSERT INTO referrals(code,referrer_id,referred_id,ts,rewarded)"
                    " VALUES(?,?,?,?,1)",
                    (ref_code, ref["id"], uid, now()))
                db.commit()
            except sqlite3.IntegrityError:
                db.execute("DELETE FROM users WHERE id=?", (uid,))
                db.commit()
                return self.send_json({"error": "referral already recorded"}, 400)
            grant_referral_reward(ref["id"])
        token = make_token(uid)
        self.send_json({"ok": True, "user_id": uid}, extra_headers={
            "Set-Cookie": f"{SESSION_COOKIE}={token}; HttpOnly; Path=/; SameSite=Lax; Max-Age={SESSION_MAX_AGE}"})

    def api_login(self):
        d = self.read_json()
        if d is None:
            return self.send_json({"error": "bad json"}, 400)
        email = (d.get("email") or "").strip().lower()
        password = d.get("password") or ""
        row = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if not row or row["banned"] or \
                not hmac.compare_digest(hash_pw(password, row["salt"]), row["pw_hash"]):
            return self.send_json({"error": "invalid email or password"}, 401)
        token = make_token(row["id"])
        self.send_json({"ok": True, "user": public_user(row)}, extra_headers={
            "Set-Cookie": f"{SESSION_COOKIE}={token}; HttpOnly; Path=/; SameSite=Lax; Max-Age={SESSION_MAX_AGE}"})

    # ---------------------------------------------------------- profile ---
    def api_profile(self, u):
        d = self.read_json()
        if d is None:
            return self.send_json({"error": "bad json"}, 400)
        name = (d.get("name") or "").strip() or u["name"]
        bio = (d.get("bio") or "")[:500]
        interests = (d.get("interests") or "")[:300]
        gender = d.get("gender") or u["gender"]
        looking_for = d.get("looking_for") or u["looking_for"]
        birthdate = (d.get("birthdate") or "").strip() or u["birthdate"]
        if gender not in ("male", "female"):
            return self.send_json({"error": "gender must be male or female"}, 400)
        if looking_for not in ("male", "female", "everyone"):
            return self.send_json({"error": "looking_for must be male/female/everyone"}, 400)
        age = calc_age(birthdate)
        if age is None or age < 18:
            return self.send_json({"error": "invalid birthdate (must stay 18+)"}, 400)
        discoverable = d.get("discoverable")
        if discoverable is None:
            discoverable = u["discoverable"] if "discoverable" in u.keys() else 1
        else:
            discoverable = 1 if discoverable else 0
        db.execute(
            "UPDATE users SET name=?, bio=?, interests=?, gender=?, looking_for=?,"
            " birthdate=?, discoverable=? WHERE id=?",
            (name, bio, interests, gender, looking_for, birthdate, discoverable, u["id"]),
        )
        db.commit()
        row = db.execute("SELECT * FROM users WHERE id=?", (u["id"],)).fetchone()
        self.send_json({"ok": True, "user": public_user(row, include_private=True)})

    def api_upload(self, u):
        ctype = self.headers.get("Content-Type", "")
        m = re.search(r"boundary=([^;]+)", ctype)
        if not m:
            return self.send_json({"error": "multipart required"}, 400)
        boundary = m.group(1).strip('"').encode()
        parts = self.parse_multipart(self.read_body(), boundary)
        photo = None
        for headers, data in parts:
            disp = headers.get("content-disposition", "")
            if 'name="photo"' in disp:
                photo = (disp, data)
                break
        if not photo:
            return self.send_json({"error": 'field "photo" missing'}, 400)
        disp, data = photo
        fn = re.search(r'filename="([^"]+)"', disp)
        ext = os.path.splitext(fn.group(1) if fn else "")[1].lower()
        if ext not in ALLOWED_PHOTO_EXT:
            return self.send_json({"error": "only jpg/jpeg/png/webp allowed"}, 400)
        if len(data) > MAX_PHOTO_BYTES:
            return self.send_json({"error": "photo too large (max 5MB)"}, 400)
        try:
            photos = json.loads(u["photos"] or "[]")
        except Exception:
            photos = []
        if len(photos) >= MAX_PHOTOS:
            return self.send_json({"error": f"max {MAX_PHOTOS} photos"}, 400)
        fname = secrets.token_hex(8) + ext
        with open(os.path.join(UPLOADS, fname), "wb") as f:
            f.write(data)
        photos.append(fname)
        db.execute("UPDATE users SET photos=? WHERE id=?", (json.dumps(photos), u["id"]))
        db.commit()
        self.send_json({"ok": True, "url": "/uploads/" + fname,
                        "photos": ["/uploads/" + p for p in photos]})

    # ---------------------------------------------------------- swipe -----
    def api_swipe(self, u):
        d = self.read_json()
        if d is None:
            return self.send_json({"error": "bad json"}, 400)
        try:
            target_id = int(d.get("target_id", 0))
        except (ValueError, TypeError):
            target_id = 0
        liked = bool(d.get("liked"))
        if target_id == u["id"]:
            return self.send_json({"error": "cannot swipe yourself"}, 400)
        target = db.execute("SELECT * FROM users WHERE id=? AND banned=0",
                            (target_id,)).fetchone()
        if not target:
            return self.send_json({"error": "no such user"}, 404)
        if db.execute("SELECT id FROM blocks WHERE (blocker_id=? AND blocked_id=?) OR (blocker_id=? AND blocked_id=?)",
                      (u["id"], target_id, target_id, u["id"])).fetchone():
            return self.send_json({"error": "user unavailable"}, 403)
        # free like limit (only counts likes, last 24h)
        if liked and not is_premium(u):
            day_ago = now() - 86400
            n = db.execute(
                "SELECT COUNT(*) c FROM swipes WHERE swiper_id=? AND liked=1 AND ts>?",
                (u["id"], day_ago)).fetchone()["c"]
            if n >= FREE_LIKES_PER_DAY:
                return self.send_json(
                    {"error": f"daily like limit reached ({FREE_LIKES_PER_DAY}) — go Premium for unlimited",
                     "upgrade": True}, 402)
        db.execute(
            "INSERT OR IGNORE INTO swipes(swiper_id,target_id,liked,ts) VALUES(?,?,?,?)",
            (u["id"], target_id, 1 if liked else 0, now()))
        db.commit()
        matched = False
        match_id = None
        if liked:
            rev = db.execute(
                "SELECT id FROM swipes WHERE swiper_id=? AND target_id=? AND liked=1",
                (target_id, u["id"])).fetchone()
            if rev:
                a, b = min(u["id"], target_id), max(u["id"], target_id)
                cur = db.execute(
                    "INSERT OR IGNORE INTO matches(user_a,user_b,ts) VALUES(?,?,?)",
                    (a, b, now()))
                db.commit()
                row = db.execute(
                    "SELECT id FROM matches WHERE user_a=? AND user_b=?", (a, b)).fetchone()
                matched, match_id = True, row["id"]
        self.send_json({"ok": True, "matched": matched, "match_id": match_id})

    # ---------------------------------------------------------- chat ------
    def api_message(self, u):
        d = self.read_json()
        if d is None:
            return self.send_json({"error": "bad json"}, 400)
        try:
            mid = int(d.get("match_id", 0))
        except (ValueError, TypeError):
            mid = 0
        text = (d.get("text") or "").strip()
        if not text:
            return self.send_json({"error": "empty message"}, 400)
        if len(text) > 500:
            return self.send_json({"error": "message too long (max 500 chars)"}, 400)
        kind = (d.get("kind") or "text").strip()
        if kind not in ("text", "game_invite"):
            # 'gift' messages are created server-side only (see api_gift_send)
            return self.send_json({"error": "bad kind"}, 400)
        extra = {}
        if kind == "game_invite":
            try:
                extra = json.loads(d.get("extra") or "{}")
            except Exception:
                return self.send_json({"error": "bad extra json"}, 400)
            if not isinstance(extra, dict) or extra.get("game") not in GAMES:
                return self.send_json({"error": "bad game invite"}, 400)
            try:
                extra["session_id"] = int(extra.get("session_id", 0))
            except (ValueError, TypeError):
                return self.send_json({"error": "bad session_id"}, 400)
            # the session must belong to this match and involve the sender
            gs = db.execute("SELECT * FROM game_sessions WHERE id=?",
                            (extra["session_id"],)).fetchone()
            if not gs or gs["match_id"] != mid or \
                    u["id"] not in (gs["player_a"], gs["player_b"]):
                return self.send_json({"error": "no such game session"}, 404)
        m = db.execute(
            "SELECT * FROM matches WHERE id=? AND (user_a=? OR user_b=?)",
            (mid, u["id"], u["id"])).fetchone()
        if not m:
            return self.send_json({"error": "no such match"}, 404)
        cur = db.execute(
            "INSERT INTO messages(match_id,sender_id,text,ts,kind,extra) VALUES(?,?,?,?,?,?)",
            (mid, u["id"], text, now(), kind, json.dumps(extra)))
        db.commit()
        self.send_json({"ok": True, "id": cur.lastrowid, "ts": now()})

    # ---------------------------------------------------------- safety ----
    def api_report(self, u):
        d = self.read_json()
        if d is None:
            return self.send_json({"error": "bad json"}, 400)
        try:
            target_id = int(d.get("target_id", 0))
        except (ValueError, TypeError):
            target_id = 0
        reason = (d.get("reason") or "")[:300]
        if target_id == u["id"] or not db.execute(
                "SELECT id FROM users WHERE id=?", (target_id,)).fetchone():
            return self.send_json({"error": "no such user"}, 404)
        db.execute("INSERT INTO reports(reporter_id,target_id,reason,ts) VALUES(?,?,?,?)",
                   (u["id"], target_id, reason, now()))
        db.commit()
        self.send_json({"ok": True})

    def api_block(self, u):
        d = self.read_json()
        if d is None:
            return self.send_json({"error": "bad json"}, 400)
        try:
            target_id = int(d.get("target_id", 0))
        except (ValueError, TypeError):
            target_id = 0
        if target_id == u["id"] or not db.execute(
                "SELECT id FROM users WHERE id=?", (target_id,)).fetchone():
            return self.send_json({"error": "no such user"}, 404)
        db.execute("INSERT OR IGNORE INTO blocks(blocker_id,blocked_id) VALUES(?,?)",
                   (u["id"], target_id))
        a, b = min(u["id"], target_id), max(u["id"], target_id)
        db.execute("DELETE FROM matches WHERE user_a=? AND user_b=?", (a, b))
        db.commit()
        self.send_json({"ok": True})

    # ---------------------------------------------------------- call -------
    def api_call_signal(self, u):
        d = self.read_json()
        if d is None:
            return self.send_json({"error": "bad json"}, 400)
        try:
            mid = int(d.get("match_id", 0))
        except (ValueError, TypeError):
            mid = 0
        kind = (d.get("kind") or "").strip()
        payload = str(d.get("payload") or "")[:20000]
        if kind not in CALL_KINDS:
            return self.send_json({"error": "bad kind (ring/offer/answer/ice/hangup)"}, 400)
        m = db.execute(
            "SELECT * FROM matches WHERE id=? AND (user_a=? OR user_b=?)",
            (mid, u["id"], u["id"])).fetchone()
        if not m:
            return self.send_json({"error": "no such match"}, 403)
        cur = db.execute(
            "INSERT INTO signals(match_id,sender_id,kind,payload,ts) VALUES(?,?,?,?,?)",
            (mid, u["id"], kind, payload, now()))
        db.commit()
        self.send_json({"ok": True, "id": cur.lastrowid})

    # ---------------------------------------------------------- games -----
    def api_game_start(self, u):
        d = self.read_json()
        if d is None:
            return self.send_json({"error": "bad json"}, 400)
        try:
            mid = int(d.get("match_id", 0))
        except (ValueError, TypeError):
            mid = 0
        game = (d.get("game") or "").strip()
        if game not in GAMES:
            return self.send_json({"error": "unknown game (tictactoe/rps)"}, 400)
        m = self.match_of(u, mid)
        if not m:
            return self.send_json({"error": "no such match"}, 404)
        other = m["user_b"] if m["user_a"] == u["id"] else m["user_a"]
        state = new_game_state(game, u["id"])
        cur = db.execute(
            """INSERT INTO game_sessions(match_id,game,player_a,player_b,state,status,ts,updated_ts)
               VALUES(?,?,?,?,?,'active',?,?)""",
            (mid, game, u["id"], other, json.dumps(state), now(), now()))
        db.commit()
        gs = db.execute("SELECT * FROM game_sessions WHERE id=?",
                        (cur.lastrowid,)).fetchone()
        self.send_json({"ok": True, "session": self.public_session(gs, u["id"])})

    def api_game_move(self, u):
        d = self.read_json()
        if d is None:
            return self.send_json({"error": "bad json"}, 400)
        try:
            sid = int(d.get("session_id", 0))
        except (ValueError, TypeError):
            sid = 0
        move = d.get("move")
        gs = self.game_session_for(u, sid)
        if not gs:
            return self.send_json({"error": "no such game"}, 403)
        if gs["status"] == "finished":
            return self.send_json({"error": "game already finished"}, 400)
        state = json.loads(gs["state"])
        if gs["game"] == "tictactoe":
            err, new_state = self.ttt_move(gs, state, u["id"], move)
        else:
            err, new_state = self.rps_move(gs, state, u["id"], move)
        if err:
            return self.send_json({"error": err}, 400)  # state unchanged
        db.execute(
            "UPDATE game_sessions SET state=?, status=?, winner_id=?, updated_ts=? WHERE id=?",
            (json.dumps(new_state["state"]), new_state["status"],
             new_state["winner"], now(), gs["id"]))
        db.commit()
        gs = db.execute("SELECT * FROM game_sessions WHERE id=?", (gs["id"],)).fetchone()
        self.send_json({"ok": True, "session": self.public_session(gs, u["id"])})

    def ttt_move(self, gs, state, uid, move):
        """Returns (error, result). result={state,status,winner}; state unchanged on error."""
        board, turn = state["board"], state["turn"]
        if turn != uid:
            return "not your turn", None
        try:
            cell = int((move or {}).get("cell", -1))
        except (ValueError, TypeError, AttributeError):
            return "bad move (need {cell: 0-8})", None
        if not 0 <= cell <= 8:
            return "bad move (cell must be 0-8)", None
        if board[cell] is not None:
            return "cell already taken", None
        board = list(board)
        board[cell] = "X" if uid == gs["player_a"] else "O"
        w = ttt_winner(board)
        if w:
            return None, {"state": {"board": board, "turn": turn},
                          "status": "finished", "winner": uid}
        if all(c is not None for c in board):
            return None, {"state": {"board": board, "turn": turn},
                          "status": "finished", "winner": None}  # draw
        other = gs["player_b"] if uid == gs["player_a"] else gs["player_a"]
        return None, {"state": {"board": board, "turn": other},
                      "status": "active", "winner": None}

    def rps_move(self, gs, state, uid, move):
        """Returns (error, result). result={state,status,winner}; state unchanged on error."""
        choice = (move or {}).get("choice") if isinstance(move, dict) else None
        if choice not in RPS_BEATS:
            return "bad move (choice must be rock/paper/scissors)", None
        key = str(uid)
        if key in state["choices"]:
            return "you already chose this round", None
        choices = dict(state["choices"])
        choices[key] = choice
        score = dict(state["score"])
        rnd, status, winner = state["round"], "active", None
        other = gs["player_b"] if uid == gs["player_a"] else gs["player_a"]
        if str(other) in choices:
            c1, c2 = choices[str(gs["player_a"])], choices[str(gs["player_b"])]
            if c1 != c2:
                side = "a" if RPS_BEATS[c1] == c2 else "b"
                score[side] += 1
            choices = {}
            rnd += 1
            if score["a"] >= RPS_WIN_SCORE:
                status, winner = "finished", gs["player_a"]
            elif score["b"] >= RPS_WIN_SCORE:
                status, winner = "finished", gs["player_b"]
        new_state = {"choices": choices, "round": rnd, "score": score}
        return None, {"state": new_state, "status": status, "winner": winner}

    # ---------------------------------------------------------- gifts -----
    def api_gift_send(self, u):
        d = self.read_json()
        if d is None:
            return self.send_json({"error": "bad json"}, 400)
        try:
            mid = int(d.get("match_id", 0))
        except (ValueError, TypeError):
            mid = 0
        gift_id = (d.get("gift_id") or "").strip()
        gift = GIFT_BY_ID.get(gift_id)
        if not gift:
            return self.send_json({"error": "unknown gift"}, 400)
        if not self.match_of(u, mid):
            return self.send_json({"error": "no such match"}, 403)
        balance = get_wallet(u["id"])
        if balance < gift["price"]:
            return self.send_json({"error": "insufficient coins", "coins": balance}, 402)
        coins_left = add_coins(u["id"], -gift["price"])
        extra = {"gift_id": gift["id"], "emoji": gift["emoji"], "name": gift["name"]}
        db.execute(
            "INSERT INTO messages(match_id,sender_id,text,ts,kind,extra) VALUES(?,?,?,?,?,?)",
            (mid, u["id"], f"sent a {gift['name']} {gift['emoji']}", now(),
             "gift", json.dumps(extra)))
        db.commit()
        self.send_json({"ok": True, "coins_left": coins_left})

    def api_grant_coins(self):
        d = self.read_json()
        if d is None:
            return self.send_json({"error": "bad json"}, 400)
        if not hmac.compare_digest(str(d.get("admin_token") or ""),
                                   CONFIG.get("admin_token") or ""):
            return self.send_json({"error": "forbidden"}, 403)
        email = (d.get("email") or "").strip().lower()
        try:
            coins = int(d.get("coins", 0))
        except (ValueError, TypeError):
            return self.send_json({"error": "bad coins amount"}, 400)
        row = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if not row:
            return self.send_json({"error": "no such user"}, 404)
        self.send_json({"ok": True, "coins": add_coins(row["id"], coins)})

    # ---------------------------------------------------------- premium ---
    def api_grant_premium(self):
        d = self.read_json()
        if d is None:
            return self.send_json({"error": "bad json"}, 400)
        if not hmac.compare_digest(str(d.get("admin_token") or ""),
                                   CONFIG.get("admin_token") or ""):
            return self.send_json({"error": "forbidden"}, 403)
        email = (d.get("email") or "").strip().lower()
        try:
            days = int(d.get("days", 30))
        except (ValueError, TypeError):
            days = 30
        row = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if not row:
            return self.send_json({"error": "no such user"}, 404)
        until = max(now(), row["premium_until"]) + days * 86400
        db.execute("UPDATE users SET is_premium=1, premium_until=? WHERE id=?",
                   (until, row["id"]))
        db.commit()
        self.send_json({"ok": True, "premium_until": until})

    # ============================================================= DELETE ==
    def do_DELETE(self):
        pu = urlparse(self.path)
        if pu.path != "/api/photo":
            return self.send_error(404)
        u = self.require_user()
        if not u:
            return
        d = self.read_json()
        if d is None:
            return self.send_json({"error": "bad json"}, 400)
        filename = os.path.basename(str(d.get("filename") or ""))
        try:
            photos = json.loads(u["photos"] or "[]")
        except Exception:
            photos = []
        if filename not in photos:
            return self.send_json({"error": "no such photo"}, 404)
        photos.remove(filename)
        try:
            os.remove(os.path.join(UPLOADS, filename))
        except OSError:
            pass
        db.execute("UPDATE users SET photos=? WHERE id=?", (json.dumps(photos), u["id"]))
        db.commit()
        self.send_json({"ok": True, "photos": ["/uploads/" + p for p in photos]})


if __name__ == "__main__":
    os.makedirs(UPLOADS, exist_ok=True)
    # On Render/hosting platforms PORT comes from the environment: bind 0.0.0.0.
    # Local runs keep the safer 127.0.0.1 default.
    host = "0.0.0.0" if "PORT" in os.environ else "127.0.0.1"
    srv = ThreadingHTTPServer((host, PORT), H)
    print(f"DateSwipe running: http://{host}:{PORT}")
    print(f"Admin token (in config.json): {CONFIG['admin_token']}")
    print("Press Ctrl+C to stop.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
