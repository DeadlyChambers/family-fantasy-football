"""Thanksgiving pick'em web app.

One roster per person, changeable until the first kickoff of the day; after
that only the commish can reopen it. The Everyone page hides rosters until
that kickoff, then shows every roster with live fantasy points.

Accepted risk: there are no passwords. Typing a name logs in as that person,
so anyone with the link can open or change another person's team before
kickoff, and can act as the commish by typing the commish's name.
"""
import argparse
import configparser
import functools
import json
import logging
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for

import espn

ROOT = Path(__file__).parent
DB_PATH = ROOT / "pickem.db"
POOL_PATH = ROOT / "pickem_pool.json"
SECRET_PATH = ROOT / ".pickem_secret"

SLOTS = (
    ("QB", "QB"),
    ("RB1", "RB"),
    ("RB2", "RB"),
    ("WR1", "WR"),
    ("WR2", "WR"),
    ("TE", "TE"),
    ("DEF", "DEF"),
    ("K", "K"),
)
SCORE_TTL_SECONDS = 60
MAX_NAME_LENGTH = 30

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    is_commish INTEGER NOT NULL DEFAULT 0,
    unlocked INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS picks (
    user_id INTEGER PRIMARY KEY REFERENCES users(id),
    slots TEXT NOT NULL,
    submitted_at TEXT NOT NULL
);
"""

log = logging.getLogger(__name__)


def connect(db_path):
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    return db


def add_user(db, name):
    """Create the account; an existing account is left alone."""
    db.execute("INSERT OR IGNORE INTO users (name) VALUES (?)", (name.strip(),))


def kickoff(game):
    return datetime.fromisoformat(game["kickoff"].replace("Z", "+00:00"))


def options_by_position(pool):
    return {
        position: sorted(
            (p for p in pool["players"] if p["pos"] == position),
            key=lambda p: (-(p.get("proj") or 0), p["name"]),
        )
        for position in {position for _, position in SLOTS}
    }


def validate_picks(form, players):
    slots = {}
    for slot, position in SLOTS:
        player = players.get(form.get(slot, ""))
        if player is None or player["pos"] != position:
            return None, f"Choose a player for {slot}."
        if player["id"] in slots.values():
            return None, f"{player['name']} is on your team twice."
        slots[slot] = player["id"]
    return slots, None


def roster_view(slots, players, points):
    rows = [
        {"slot": slot, "player": players.get(slots.get(slot)), "points": points.get(slots.get(slot), 0)}
        for slot, _ in SLOTS
    ]
    return rows, round(sum(row["points"] for row in rows), 2)


class LiveScores:
    """Fantasy points per player id, asking ESPN at most once per SCORE_TTL_SECONDS per game."""

    def __init__(self, games, fetch, now):
        self._games = games
        self._fetch = fetch
        self._now = now
        self._lock = threading.Lock()
        self._results = {}
        self._asked_at = {}
        self._failed = set()

    def snapshot(self):
        """Return (points by player id, status text by game id, True when a game's scores are stale)."""
        with self._lock:
            now = self._now()
            for game in self._games:
                if now >= kickoff(game) and self._is_due(game["id"], now):
                    self._refresh(game["id"], now)
            points = {}
            details = {}
            for game_id, result in self._results.items():
                points.update(result["points"])
                details[game_id] = result["detail"]
            return points, details, bool(self._failed)

    def _is_due(self, game_id, now):
        result = self._results.get(game_id)
        if result and result["state"] == "post":
            return False
        asked = self._asked_at.get(game_id)
        return asked is None or (now - asked).total_seconds() >= SCORE_TTL_SECONDS

    def _refresh(self, game_id, now):
        self._asked_at[game_id] = now
        try:
            self._results[game_id] = espn.parse_fantasy_points(self._fetch(f"summary?event={game_id}"))
            self._failed.discard(game_id)
        except (OSError, ValueError, KeyError):
            # The last good scores stay on the page and the leaderboard says they are delayed.
            log.exception("ESPN score refresh failed for game %s", game_id)
            self._failed.add(game_id)


def create_app(db_path, pool, now=None, fetch=espn.fetch_json, secret_key=None):
    app = Flask(__name__)
    app.secret_key = secret_key or secrets.token_hex(32)
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(days=7),
    )
    now = now or (lambda: datetime.now(timezone.utc))
    players = {player["id"]: player for player in pool["players"]}
    options = options_by_position(pool)
    reveal_at = min(kickoff(game) for game in pool["games"])
    live = LiveScores(pool["games"], fetch, now)

    db = connect(db_path)
    db.executescript(SCHEMA)
    db.close()

    def revealed():
        return now() >= reveal_at

    def load_slots(user_id):
        row = g.db.execute("SELECT slots FROM picks WHERE user_id = ?", (user_id,)).fetchone()
        return json.loads(row["slots"]) if row else None

    def can_edit():
        return bool(g.user["unlocked"]) or not revealed()

    def commish_only(view):
        @functools.wraps(view)
        def guarded(*args, **kwargs):
            if not g.user["is_commish"]:
                abort(403)
            return view(*args, **kwargs)

        return guarded

    @app.context_processor
    def template_globals():
        def csrf_token():
            return session.setdefault("csrf", secrets.token_hex(16))

        return {"csrf_token": csrf_token, "user": g.get("user"), "reveal_at": reveal_at.isoformat()}

    @app.before_request
    def gate_request():
        g.db = connect(db_path)
        g.user = None
        if "user_id" in session:
            g.user = g.db.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
        if request.method == "POST":
            expected = session.get("csrf", "")
            sent = request.form.get("csrf", "")
            if not expected or not secrets.compare_digest(sent.encode(), expected.encode()):
                abort(400)
        if g.user is None and request.endpoint != "login":
            return redirect(url_for("login"))
        return None

    @app.teardown_request
    def close_db(_error):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            found = g.db.execute("SELECT * FROM users WHERE name = ?", (name,)).fetchone()
            if found is None and not 1 <= len(name) <= MAX_NAME_LENGTH:
                flash(f"Your name needs 1 to {MAX_NAME_LENGTH} characters.")
            elif found is None and revealed():
                flash("New teams closed at kickoff. Ask the commish to add you.")
            else:
                if found is None:
                    add_user(g.db, name)
                    g.db.commit()
                    found = g.db.execute("SELECT * FROM users WHERE name = ?", (name,)).fetchone()
                session.clear()
                session["user_id"] = found["id"]
                session.permanent = True
                return redirect(url_for("home"))
        return render_template("login.html")

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    def render_home(chosen, status=200):
        slots = load_slots(g.user["id"])
        started = revealed()
        points = live.snapshot()[0] if started else {}
        rows, total = roster_view(slots, players, points) if slots else ([], 0)
        page = render_template(
            "home.html",
            editable=can_edit(),
            chosen=chosen if chosen is not None else (slots or {}),
            slots=SLOTS,
            options=options,
            rows=rows,
            total=total,
            started=started,
        )
        return page, status

    @app.route("/")
    def home():
        return render_home(None)

    @app.post("/picks")
    def submit_picks():
        if not can_edit():
            flash("Your team is locked. Ask the commish to reopen it.")
            return redirect(url_for("home"))
        started = revealed()
        slots, error = validate_picks(request.form, players)
        if error:
            flash(error)
            return render_home(request.form, 400)
        g.db.execute(
            "INSERT INTO picks (user_id, slots, submitted_at) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET slots = excluded.slots, submitted_at = excluded.submitted_at",
            (g.user["id"], json.dumps(slots), now().isoformat()),
        )
        g.db.execute("UPDATE users SET unlocked = 0 WHERE id = ?", (g.user["id"],))
        g.db.commit()
        if started:
            flash("Your team is submitted and locked.")
        else:
            flash("Your team is saved. You can change it until kickoff.")
        return redirect(url_for("home"))

    @app.route("/teams")
    def teams():
        users = g.db.execute("SELECT id, name FROM users ORDER BY name").fetchall()
        picks = {
            row["user_id"]: json.loads(row["slots"])
            for row in g.db.execute("SELECT user_id, slots FROM picks")
        }
        if not revealed():
            waiting = [{"name": u["name"], "submitted": u["id"] in picks} for u in users]
            return render_template("teams.html", revealed=False, waiting=waiting)
        points, details, delayed = live.snapshot()
        entries = []
        for member in users:
            slots = picks.get(member["id"])
            rows, total = roster_view(slots, players, points) if slots else ([], 0)
            entries.append({"name": member["name"], "rows": rows, "total": total})
        entries.sort(key=lambda entry: (-entry["total"], entry["name"].lower()))
        games = [
            {"short": game["short"], "kickoff": game["kickoff"], "detail": details.get(game["id"])}
            for game in pool["games"]
        ]
        return render_template("teams.html", revealed=True, entries=entries, games=games, delayed=delayed)

    @app.route("/commish")
    @commish_only
    def commish():
        members = g.db.execute(
            "SELECT u.id, u.name, u.unlocked, p.user_id IS NOT NULL AS submitted "
            "FROM users u LEFT JOIN picks p ON p.user_id = u.id ORDER BY u.name"
        ).fetchall()
        return render_template("commish.html", members=members)

    def member_or_404(user_id):
        member = g.db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if member is None:
            abort(404)
        return member

    @app.post("/commish/unlock/<int:user_id>")
    @commish_only
    def commish_unlock(user_id):
        member = member_or_404(user_id)
        g.db.execute("UPDATE users SET unlocked = 1 WHERE id = ?", (user_id,))
        g.db.commit()
        flash(f"{member['name']} can change their team once, then it locks again.")
        return redirect(url_for("commish"))

    @app.post("/commish/add")
    @commish_only
    def commish_add():
        name = request.form.get("name", "").strip()
        if not 1 <= len(name) <= MAX_NAME_LENGTH:
            flash(f"A name needs 1 to {MAX_NAME_LENGTH} characters.")
        else:
            add_user(g.db, name)
            g.db.commit()
            flash(f"{name} can log in with their name.")
        return redirect(url_for("commish"))

    return app


def init_command(args):
    pool = espn.build_pool(args.date)
    if not pool["games"]:
        raise SystemExit(f"ESPN lists no NFL games on {args.date}; pass --date YYYYMMDD.")
    espn.add_projections(pool)
    POOL_PATH.write_text(json.dumps(pool, indent=1), encoding="utf-8")

    teams_config = configparser.RawConfigParser(strict=False)
    teams_config.read(args.teams_config)
    names = teams_config.sections()
    db = connect(DB_PATH)
    db.executescript(SCHEMA)
    for name in [*names, args.commish]:
        add_user(db, name)
    db.execute("UPDATE users SET is_commish = 1 WHERE name = ?", (args.commish,))
    db.commit()
    members = [row["name"] for row in db.execute("SELECT name FROM users ORDER BY name")]
    db.close()

    print(f"Games on {args.date}:")
    for game in pool["games"]:
        print(f"  {game['short']}  kickoff {game['kickoff']}")
    print(f"Players loaded: {len(pool['players'])}")
    print(f"Accounts ({len(members)}): {', '.join(members)}; commish: {args.commish}")


def projections_command(args):
    if not POOL_PATH.exists():
        raise SystemExit("No player pool yet. Run: python pickem.py init")
    pool = json.loads(POOL_PATH.read_text(encoding="utf-8"))
    week = espn.add_projections(pool)
    POOL_PATH.write_text(json.dumps(pool, indent=1), encoding="utf-8")
    ranked = sum(1 for player in pool["players"] if player["proj"] is not None)
    print(f"Week {week} projections set for {ranked} of {len(pool['players'])} players. Restart serve to show them.")


def serve_command(args):
    from waitress import serve

    if not POOL_PATH.exists():
        raise SystemExit("No player pool yet. Run: python pickem.py init")
    if not SECRET_PATH.exists():
        SECRET_PATH.write_text(secrets.token_hex(32), encoding="utf-8")
    app = create_app(
        DB_PATH,
        json.loads(POOL_PATH.read_text(encoding="utf-8")),
        secret_key=SECRET_PATH.read_text(encoding="utf-8").strip(),
    )
    print(f"Pick'em running at http://{args.host}:{args.port}")
    serve(app, host=args.host, port=args.port, threads=8)


def main():
    parser = argparse.ArgumentParser(description="Thanksgiving pick'em web app")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="load the day's players from ESPN and create the accounts")
    init.add_argument("--date", default=datetime.now().strftime("%Y%m%d"), help="game day as YYYYMMDD")
    init.add_argument("--teams-config", default=str(ROOT / "teams.ini"), help="file whose [sections] are the people")
    init.add_argument("--commish", default="Shane", help="account that can reopen teams")
    init.set_defaults(run=init_command)
    projections = commands.add_parser("projections", help="refresh ESPN's projected points in the player pool")
    projections.set_defaults(run=projections_command)
    serve = commands.add_parser("serve", help="run the web app")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", default=8080, type=int)
    serve.set_defaults(run=serve_command)
    args = parser.parse_args()
    args.run(args)


if __name__ == "__main__":
    main()
