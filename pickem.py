"""Thanksgiving pick'em web app.

One roster per person, changeable until the first kickoff of the day; after
that only the commish can reopen it, change it or delete the team, and each
commish change is listed on the team. The Everyone page hides rosters until
that kickoff, then shows every picked roster with live fantasy points. Each person
also guesses the last game's winner and total score, which orders equal totals.
Picking each game's winner is a separate contest with its own standings.
The hall of fame page lists each year's winner from hall_of_fame.json, which
outlives pickem.db; the commish saves a finished contest into it.

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
import subprocess
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Flask, Response, abort, flash, g, redirect, render_template, request, session, url_for

import espn

ROOT = Path(__file__).parent
DB_PATH = ROOT / "pickem.db"
POOL_PATH = ROOT / "pickem_pool.json"
SECRET_PATH = ROOT / ".pickem_secret"
HALL_PATH = ROOT / "hall_of_fame.json"

SLOTS = (
    ("QB", "QB"),
    ("RB1", "RB"),
    ("RB2", "RB"),
    ("WR1", "WR"),
    ("WR2", "WR"),
    ("TE", "TE"),
    ("FLEX", "FLEX"),
    ("DEF", "DEF"),
    ("K", "K"),
)
FLEX_POSITIONS = ("RB", "WR", "TE")
SCORE_TTL_SECONDS = 60
CHANGE_SHOWN_SECONDS = 300
MAX_NAME_LENGTH = 30
MAX_TIEBREAK_TOTAL = 200
OVER_UNDER_SIDES = ("over", "under")
MAX_TEAM_NAME_LENGTH = 40
# The My team page shrinks a picture to a small square before sending it, so a stored one is far under this.
MAX_AVATAR_BYTES = 512 * 1024
# A whole request above this is refused before it is read; a phone photo sent without shrinking fits under it.
MAX_UPLOAD_BYTES = 12 * 1024 * 1024
# Leading bytes of the picture types a browser shows as a still image. SVG is left out: it can carry script.
IMAGE_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    is_commish INTEGER NOT NULL DEFAULT 0,
    unlocked INTEGER NOT NULL DEFAULT 0,
    team_name TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS avatars (
    user_id INTEGER PRIMARY KEY REFERENCES users(id),
    mime TEXT NOT NULL,
    image BLOB NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS picks (
    user_id INTEGER PRIMARY KEY REFERENCES users(id),
    slots TEXT NOT NULL,
    submitted_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tiebreakers (
    user_id INTEGER PRIMARY KEY REFERENCES users(id),
    winner TEXT NOT NULL,
    total INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS game_picks (
    user_id INTEGER PRIMARY KEY REFERENCES users(id),
    picks TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS roster_edits (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    edited_at TEXT NOT NULL,
    note TEXT NOT NULL,
    players TEXT NOT NULL DEFAULT '[]'
);
"""
# Columns added after their table first shipped; an older database gains them at startup.
ADDED_COLUMNS = (
    ("roster_edits", "players", "TEXT NOT NULL DEFAULT '[]'"),
    ("users", "team_name", "TEXT NOT NULL DEFAULT ''"),
)
HIDDEN_NOTE = "changed a spot, shown when that game kicks off"
USER_TABLES = ("picks", "tiebreakers", "game_picks", "roster_edits", "avatars")

log = logging.getLogger(__name__)


UNVERSIONED = "unversioned"


def app_version(root=ROOT):
    """Version read from git as "1.<commits on HEAD> (<short hash>)", so every commit changes it.

    "+changes" after the hash means tracked files differ from that commit.
    """

    def git(*args):
        try:
            done = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)
        except OSError:
            return ""
        return done.stdout.strip() if done.returncode == 0 else ""

    count = git("rev-list", "--count", "HEAD")
    # --exclude=* skips every tag, so the answer is always the bare hash
    commit = git("describe", "--always", "--exclude=*", "--dirty=+changes")
    return f"1.{count} ({commit})" if count and commit else UNVERSIONED


def connect(db_path):
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    return db


def add_user(db, name):
    """Create the account; an existing account is left alone."""
    db.execute("INSERT OR IGNORE INTO users (name) VALUES (?)", (name.strip(),))


def parse_time(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def kickoff(game):
    return parse_time(game["kickoff"])


def eligible(position):
    return FLEX_POSITIONS if position == "FLEX" else (position,)


def options_by_position(pool):
    return {
        position: sorted(
            (p for p in pool["players"] if p["pos"] in eligible(position)),
            key=lambda p: (-(p.get("proj") or 0), p["name"]),
        )
        for position in {position for _, position in SLOTS}
    }


def validate_picks(form, players, allow_empty=False):
    slots = {}
    for slot, position in SLOTS:
        choice = form.get(slot, "")
        if allow_empty and not choice:
            continue
        player = players.get(choice)
        if player is None or player["pos"] not in eligible(position):
            return None, f"Choose a player for {slot}."
        if player["id"] in slots.values():
            return None, f"{player['name']} is on your team twice."
        slots[slot] = player["id"]
    return slots, None


def edit_notes(before, after, players):
    """One (phrase, player ids it names) pair per roster spot that differs, such as "added X at QB, replacing Y"."""

    def name(player_id):
        player = players.get(player_id)
        return player["name"] if player else "a player no longer listed"

    notes = []
    for slot, _ in SLOTS:
        old, new = before.get(slot), after.get(slot)
        if old == new:
            continue
        if new is None:
            notes.append((f"removed {name(old)} from {slot}", [old]))
        elif old is None:
            notes.append((f"added {name(new)} at {slot}", [new]))
        else:
            notes.append((f"added {name(new)} at {slot}, replacing {name(old)}", [new, old]))
    return notes


def validate_tiebreaker(form, game):
    winner = form.get("winner", "")
    total = form.get("total", "").strip()
    if winner not in [team["abbr"] for team in game["teams"]]:
        return None, f"Choose who wins {game['short']}."
    if not (total.isascii() and total.isdigit() and int(total) <= MAX_TIEBREAK_TOTAL):
        return None, f"The total score is a whole number from 0 to {MAX_TIEBREAK_TOTAL}."
    return {"winner": winner, "total": int(total)}, None


def validate_game_picks(form, games):
    picks = {}
    for game in games:
        pick = form.get(f"pick-{game['id']}", "")
        if not pick:
            continue
        if pick not in [team["abbr"] for team in game["teams"]]:
            return None, f"Choose a team playing in {game['short']}."
        picks[game["id"]] = pick
    for game in games:
        side = form.get(f"ou-{game['id']}", "")
        if not side:
            continue
        if side not in OVER_UNDER_SIDES or game.get("over_under") is None:
            return None, f"Choose over or under for {game['short']}."
        picks[f"ou-{game['id']}"] = side
    return picks, None


def game_pick_view(picks, games, results):
    """Return (one cell per game, number right); "right" and "side_right" stay None until the game is final.

    A final total equal to the line makes neither side right.
    """
    cells = []
    for game in games:
        pick = picks.get(game["id"])
        side = picks.get(f"ou-{game['id']}")
        line = game.get("over_under")
        result = results.get(game["id"], {})
        final = result.get("state") == "post"
        right = pick == result["winner"] if pick and final else None
        side_right = None
        if side and line is not None and final:
            total = sum(result["scores"].values())
            side_right = total > line if side == "over" else total < line
        cells.append(
            {"short": game["short"], "pick": pick, "right": right, "line": line, "side": side, "side_right": side_right}
        )
    return cells, sum(1 for cell in cells for key in ("right", "side_right") if cell[key])


def tiebreak_rank(tiebreak, final):
    """Order among equal fantasy totals: the right winner first, then the closest combined score."""
    if tiebreak is None:
        return (1, float("inf"))
    actual = sum(final["scores"].values())
    return (0 if tiebreak["winner"] == final["winner"] else 1, abs(tiebreak["total"] - actual))


def has_roster(slots):
    """A spot the commish emptied leaves a roster; a person who never picked anyone has none."""
    return any(slots.get(slot) for slot, _ in SLOTS)


def load_hall(path):
    """Past contests, newest first; a missing file is an empty hall."""
    if not path.exists():
        return []
    return sorted(json.loads(path.read_text(encoding="utf-8")), key=lambda entry: -entry["year"])


def save_hall_year(path, record):
    """Put one year's result in the hall file, replacing only that year's earlier entry."""
    kept = [entry for entry in load_hall(path) if entry["year"] != record["year"]]
    hall = sorted([*kept, record], key=lambda entry: -entry["year"])
    draft = path.with_name(path.name + ".tmp")
    draft.write_text(json.dumps(hall, indent=2) + "\n", encoding="utf-8", newline="\n")
    draft.replace(path)


def player_stats(results):
    """The stat entries behind each player's points, by player id, across every game's result."""
    return {
        player_id: lines for result in results.values() for player_id, lines in result.get("stats", {}).items()
    }


def image_type(data):
    """The content type of a still picture a browser can show, read from its first bytes; None for anything else."""
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return next((mime for signature, mime in IMAGE_SIGNATURES if data.startswith(signature)), None)


def minutes_by_team(games, results):
    """Game minutes left for each team's players; a game ESPN has not been asked about yet has all of them."""
    return {
        team["abbr"]: results.get(game["id"], {}).get("minutes_left", espn.GAME_MINUTES)
        for game in games
        for team in game["teams"]
    }


def roster_view(slots, players, points, changes, stats, minutes):
    """One row per roster spot, and the team's total points.

    A row's "projected" is the points so far plus the share of ESPN's pregame
    projection that matches the game time left, so it equals the projection
    before kickoff and the points once the game is final.
    """
    rows = []
    for slot, _ in SLOTS:
        player = players.get(slots.get(slot))
        scored = points.get(slots.get(slot), 0)
        left = minutes.get(player["team"], 0) if player else 0
        ahead = (player.get("proj") or 0) * left / espn.GAME_MINUTES if player else 0
        rows.append(
            {
                "slot": slot,
                "picked": slot in slots,
                "player": player,
                "points": scored,
                "change": changes.get(slots.get(slot)),
                "stats": stats.get(slots.get(slot), []),
                "minutes": left,
                "projected": round(scored + ahead, 2),
            }
        )
    return rows, round(sum(row["points"] for row in rows), 2)


def outlook(rows):
    """A team's projected total, its game minutes left added over its players, and how many players have any."""
    return {
        "projected": round(sum(row["projected"] for row in rows), 2),
        "minutes": round(sum(row["minutes"] for row in rows)),
        "playing": sum(1 for row in rows if row["minutes"]),
    }


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
        self._answered_at = None
        self._changes = {}

    def snapshot(self):
        """Return (points by player id, status text by game id, True when scores are stale, result by game id)."""
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
            return points, details, bool(self._failed), dict(self._results)

    def updates(self):
        """Return (when ESPN last answered, points gained or lost by player id in the last CHANGE_SHOWN_SECONDS)."""
        with self._lock:
            now = self._now()
            recent = {
                player_id: change
                for player_id, (change, at) in self._changes.items()
                if (now - at).total_seconds() < CHANGE_SHOWN_SECONDS
            }
            return self._answered_at, recent

    def _is_due(self, game_id, now):
        result = self._results.get(game_id)
        if result and result["state"] == "post":
            return False
        asked = self._asked_at.get(game_id)
        return asked is None or (now - asked).total_seconds() >= SCORE_TTL_SECONDS

    def _refresh(self, game_id, now):
        self._asked_at[game_id] = now
        try:
            result = espn.parse_fantasy_points(self._fetch(f"summary?event={game_id}"))
        except (OSError, ValueError, KeyError):
            # The last good scores stay on the page and the leaderboard says they are delayed.
            log.exception("ESPN score refresh failed for game %s", game_id)
            self._failed.add(game_id)
            return
        before = self._results.get(game_id)
        # The first answer after a start has nothing to compare with, so it marks no changes.
        if before:
            for player_id, points in result["points"].items():
                change = round(points - before["points"].get(player_id, 0), 2)
                if change:
                    self._changes[player_id] = (change, now)
        self._results[game_id] = result
        self._answered_at = now
        self._failed.discard(game_id)


def create_app(
    db_path, pool, now=None, fetch=espn.fetch_json, secret_key=None, version=UNVERSIONED, hall_path=HALL_PATH
):
    app = Flask(__name__)
    app.secret_key = secret_key or secrets.token_hex(32)
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(days=7),
        MAX_CONTENT_LENGTH=MAX_UPLOAD_BYTES,
    )
    now = now or (lambda: datetime.now(timezone.utc))
    started_at = now()
    players = {player["id"]: player for player in pool["players"]}
    options = options_by_position(pool)
    lock_at = pool.get("lock_at")
    reveal_at = parse_time(lock_at) if lock_at else min(kickoff(game) for game in pool["games"])
    picks_lock = pool.get("picks_lock_at")
    picks_lock_at = parse_time(picks_lock) if picks_lock else reveal_at
    live = LiveScores(pool["games"], fetch, now)
    last_game = max(pool["games"], key=kickoff)
    year = kickoff(last_game).year
    kickoff_by_team = {team["abbr"]: kickoff(game) for game in pool["games"] for team in game["teams"]}

    db = connect(db_path)
    db.executescript(SCHEMA)
    for table, column, definition in ADDED_COLUMNS:
        if column not in {found["name"] for found in db.execute(f"PRAGMA table_info({table})")}:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    db.commit()
    db.close()

    def revealed():
        return now() >= reveal_at

    def tiebreak_open():
        return now() < kickoff(last_game)

    def picks_open():
        return now() < picks_lock_at

    def load_game_picks(user_id):
        row = g.db.execute("SELECT picks FROM game_picks WHERE user_id = ?", (user_id,)).fetchone()
        return json.loads(row["picks"]) if row else {}

    def load_slots(user_id):
        row = g.db.execute("SELECT slots FROM picks WHERE user_id = ?", (user_id,)).fetchone()
        return json.loads(row["slots"]) if row else None

    def load_edits():
        edits = {}
        for row in g.db.execute("SELECT user_id, edited_at, note, players FROM roster_edits ORDER BY id"):
            edits.setdefault(row["user_id"], []).append(
                {"edited_at": row["edited_at"], "note": row["note"], "players": json.loads(row["players"])}
            )
        return edits

    def record_edits(user_id, notes):
        """Store (phrase, player ids it names) pairs; the ids decide when other people may read the phrase."""
        g.db.executemany(
            "INSERT INTO roster_edits (user_id, edited_at, note, players) VALUES (?, ?, ?, ?)",
            [(user_id, now().isoformat(), note, json.dumps(named)) for note, named in notes],
        )

    def not_kicked_off():
        """Ids of players whose game has not started; other people do not see these on a roster."""
        return {p["id"] for p in pool["players"] if now() < kickoff_by_team[p["team"]]}

    def ranked_teams(points, changes, stats, minutes, final, tiebreaks):
        """People who picked a roster, best first; equal totals fall to the tiebreaker once the last game is final."""
        decided = final.get("state") == "post"
        board = []
        for row in g.db.execute(
            "SELECT u.id, u.name, u.team_name, p.slots, a.updated_at AS avatar_at "
            "FROM users u JOIN picks p ON p.user_id = u.id LEFT JOIN avatars a ON a.user_id = u.id"
        ):
            slots = json.loads(row["slots"])
            if not has_roster(slots):
                continue
            rows, total = roster_view(slots, players, points, changes, stats, minutes)
            tiebreak = tiebreaks.get(row["id"])
            board.append(
                {
                    "id": row["id"],
                    "name": row["name"],
                    "team_name": row["team_name"],
                    "avatar_at": row["avatar_at"],
                    "rows": rows,
                    "total": total,
                    "outlook": outlook(rows),
                    "tiebreak": tiebreak,
                    "rank": tiebreak_rank(tiebreak, final) if decided else (0, 0),
                }
            )
        board.sort(key=lambda entry: (-entry["total"], entry["rank"], entry["name"].lower()))
        return board

    def pickem_board(results):
        """People who made a game pick, most right first."""
        board = []
        for row in g.db.execute("SELECT u.name, p.picks FROM game_picks p JOIN users u ON u.id = p.user_id"):
            cells, right = game_pick_view(json.loads(row["picks"]), pool["games"], results)
            if any(cell["pick"] or cell["side"] for cell in cells):
                board.append({"name": row["name"], "cells": cells, "right": right})
        board.sort(key=lambda entry: (-entry["right"], entry["name"].lower()))
        return board

    def this_year():
        """This contest shaped like a hall of fame entry once every game is final; None before that."""
        if now() < kickoff(last_game):
            return None
        points, _details, _delayed, results = live.snapshot()
        if any(results.get(game["id"], {}).get("state") != "post" for game in pool["games"]):
            return None
        tiebreaks = {row["user_id"]: row for row in g.db.execute("SELECT * FROM tiebreakers")}
        board = ranked_teams(points, {}, {}, {}, results[last_game["id"]], tiebreaks)
        if not board:
            return None
        record = {
            "year": year,
            "winner": board[0]["name"],
            "scores": [{"name": entry["name"], "score": entry["total"]} for entry in board],
        }
        picks = pickem_board(results)
        if picks:
            record["pickem"] = [{"name": entry["name"], "right": entry["right"]} for entry in picks]
        return record

    def can_edit():
        return bool(g.user["unlocked"]) or not revealed()

    def late_flex_choices(slots):
        """Flex options for a locked team saved without one: players not on it whose game has not kicked off."""
        if not slots or "FLEX" in slots or can_edit():
            return None
        return [
            p
            for p in options["FLEX"]
            if p["id"] not in slots.values() and now() < kickoff_by_team[p["team"]]
        ]

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

        return {
            "csrf_token": csrf_token,
            "user": g.get("user"),
            "reveal_at": reveal_at.isoformat(),
            "picks_lock_at": picks_lock_at.isoformat(),
            "version": version,
            "started_at": started_at.isoformat(),
        }

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

    @app.errorhandler(400)
    def stale_form(_error):
        message = "That page was out of date, so nothing was saved. Go back, reload the page and try again."
        return render_template("problem.html", message=message), 400

    @app.errorhandler(413)
    def upload_too_big(_error):
        message = "That picture is too big to send, so nothing was saved. Go back and choose a smaller one."
        return render_template("problem.html", message=message), 413

    @app.errorhandler(403)
    def commish_needed(_error):
        name = g.user["name"] if g.get("user") else "nobody"
        message = (
            f"Only the commish can do that, and this browser is logged in as {name}. "
            "A browser holds one login at a time: log out, then log in as the commish."
        )
        return render_template("problem.html", message=message), 403

    @app.after_request
    def log_request(response):
        if request.method == "POST" or response.status_code >= 400:
            name = g.user["name"] if g.get("user") else "-"
            log.info("%s %s %s as %s", request.method, request.path, response.status_code, name)
        return response

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
        points, _, _, results = live.snapshot() if started else ({}, {}, False, {})
        scores_at, changes = live.updates()
        minutes = minutes_by_team(pool["games"], results)
        rows, total = (
            roster_view(slots, players, points, changes, player_stats(results), minutes) if slots else ([], 0)
        )
        tiebreak = g.db.execute("SELECT * FROM tiebreakers WHERE user_id = ?", (g.user["id"],)).fetchone()
        game_picks = load_game_picks(g.user["id"])
        avatar_row = g.db.execute("SELECT updated_at FROM avatars WHERE user_id = ?", (g.user["id"],)).fetchone()
        page = render_template(
            "home.html",
            profile_form=request.args.get("edit") == "profile",
            me={**dict(g.user), "avatar_at": avatar_row["updated_at"] if avatar_row else None},
            max_team_name=MAX_TEAM_NAME_LENGTH,
            outlook=outlook(rows),
            editable=can_edit(),
            chosen=chosen if chosen is not None else (slots or {}),
            slots=SLOTS,
            options=options,
            rows=rows,
            total=total,
            started=started,
            scores_at=scores_at.isoformat() if scores_at else None,
            edits=load_edits().get(g.user["id"], []),
            flex_choices=late_flex_choices(slots),
            tiebreak=tiebreak,
            tiebreak_open=tiebreak_open(),
            tiebreak_form=tiebreak_open() and (tiebreak is None or request.args.get("edit") == "tiebreaker"),
            last_game=last_game,
            max_total=MAX_TIEBREAK_TOTAL,
            games=pool["games"],
            game_picks=game_picks,
            pick_cells=game_pick_view(game_picks, pool["games"], results)[0],
            picks_open=picks_open(),
            picks_form=picks_open() and (not game_picks or request.args.get("edit") == "picks"),
        )
        return page, status

    @app.route("/")
    def home():
        return render_home(None)

    @app.post("/profile")
    def submit_profile():
        """Save the person's team name and picture; both are decoration, so they stay changeable after the lock."""
        team_name = " ".join(request.form.get("team_name", "").split())
        upload = request.files.get("avatar")
        image = upload.read(MAX_AVATAR_BYTES + 1) if upload else b""
        mime = image_type(image)
        if len(team_name) > MAX_TEAM_NAME_LENGTH:
            flash(f"A team name can have up to {MAX_TEAM_NAME_LENGTH} characters.")
        elif len(image) > MAX_AVATAR_BYTES:
            flash("That picture is too big. Choose a smaller one.")
        elif image and mime is None:
            flash("That file is not a picture this page can show. Choose a PNG, JPEG, GIF or WebP.")
        else:
            g.db.execute("UPDATE users SET team_name = ? WHERE id = ?", (team_name, g.user["id"]))
            if image:
                g.db.execute(
                    "INSERT INTO avatars (user_id, mime, image, updated_at) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(user_id) DO UPDATE SET mime = excluded.mime, image = excluded.image, "
                    "updated_at = excluded.updated_at",
                    (g.user["id"], mime, image, now().isoformat()),
                )
            elif request.form.get("remove_avatar"):
                g.db.execute("DELETE FROM avatars WHERE user_id = ?", (g.user["id"],))
            g.db.commit()
            flash("Your team name and picture are saved.")
            return redirect(url_for("home"))
        return redirect(url_for("home", edit="profile"))

    @app.route("/avatar/<int:user_id>")
    def avatar(user_id):
        row = g.db.execute("SELECT mime, image FROM avatars WHERE user_id = ?", (user_id,)).fetchone()
        if row is None:
            abort(404)
        response = Response(row["image"], mimetype=row["mime"])
        # The stored type came from the file's own first bytes; the browser must not guess another one.
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "private, max-age=86400"
        return response

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
        if started:
            changes = edit_notes(load_slots(g.user["id"]) or {}, slots, players)
            record_edits(
                g.user["id"],
                [(f"approved a change after reopening the team: {note}", named) for note, named in changes],
            )
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

    @app.post("/flex")
    def add_flex():
        slots = load_slots(g.user["id"])
        choices = late_flex_choices(slots)
        player = players.get(request.form.get("FLEX", ""))
        if choices is None:
            flash("Your flex cannot be changed here.")
        elif player not in choices:
            flash("Choose a flex from a game that has not kicked off.")
        else:
            slots["FLEX"] = player["id"]
            g.db.execute("UPDATE picks SET slots = ? WHERE user_id = ?", (json.dumps(slots), g.user["id"]))
            g.db.commit()
            flash(f"{player['name']} is your flex.")
        return redirect(url_for("home"))

    @app.post("/tiebreaker")
    def submit_tiebreaker():
        if not tiebreak_open():
            flash(f"The tiebreaker locked when {last_game['short']} kicked off.")
            return redirect(url_for("home"))
        tiebreak, error = validate_tiebreaker(request.form, last_game)
        if error:
            flash(error)
            return redirect(url_for("home", edit="tiebreaker"))
        g.db.execute(
            "INSERT INTO tiebreakers (user_id, winner, total) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET winner = excluded.winner, total = excluded.total",
            (g.user["id"], tiebreak["winner"], tiebreak["total"]),
        )
        g.db.commit()
        flash("Your tiebreaker is saved.")
        return redirect(url_for("home"))

    @app.post("/game-picks")
    def submit_game_picks():
        if not picks_open():
            flash("The game picks are locked.")
            return redirect(url_for("home"))
        picks, error = validate_game_picks(request.form, pool["games"])
        if error:
            flash(error)
            return redirect(url_for("home", edit="picks"))
        g.db.execute(
            "INSERT INTO game_picks (user_id, picks) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET picks = excluded.picks",
            (g.user["id"], json.dumps(picks)),
        )
        g.db.commit()
        flash("Your game picks are saved.")
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
        points, details, delayed, results = live.snapshot()
        scores_at, changes = live.updates()
        final = results.get(last_game["id"], {})
        # Other people's tiebreakers stay hidden while they can still be changed.
        tiebreaks = (
            {}
            if tiebreak_open()
            else {row["user_id"]: row for row in g.db.execute("SELECT * FROM tiebreakers")}
        )
        edits = load_edits()
        # A late flex or a commish change can still pick from a game that has not started,
        # so other people's players from that game stay hidden until it kicks off.
        unseen = not_kicked_off()
        minutes = minutes_by_team(pool["games"], results)
        entries = ranked_teams(points, changes, player_stats(results), minutes, final, tiebreaks)
        for entry in entries:
            entry["edits"] = edits.get(entry["id"], [])
            if entry["id"] != g.user["id"]:
                entry["rows"] = [
                    {**row, "player": None, "hidden": True} if row["player"] and row["player"]["id"] in unseen else row
                    for row in entry["rows"]
                ]
                entry["edits"] = [
                    {**note, "note": HIDDEN_NOTE} if unseen.intersection(note["players"]) else note
                    for note in entry["edits"]
                ]
        games = [
            {
                "short": game["short"],
                "kickoff": game["kickoff"],
                "detail": details.get(game["id"]),
                "over_under": game.get("over_under"),
            }
            for game in pool["games"]
        ]
        # Other people's game picks stay hidden while they can still be changed.
        pickem = [] if picks_open() else pickem_board(results)
        return render_template(
            "teams.html",
            revealed=True,
            compact=request.args.get("view") == "compact",
            entries=entries,
            left_off=len(users) - len(entries),
            games=games,
            delayed=delayed,
            scores_at=scores_at.isoformat() if scores_at else None,
            last_game=last_game,
            pickem=pickem,
            picks_shown=not picks_open(),
        )

    @app.route("/hall-of-fame")
    def hall_of_fame():
        saved = load_hall(hall_path)
        current = this_year()
        years = [entry for entry in saved if not (current and entry["year"] == year)]
        if current:
            years.insert(0, current)
        return render_template(
            "hall_of_fame.html",
            years=years,
            year=year,
            current=current,
            on_file=any(entry["year"] == year for entry in saved),
        )

    @app.post("/commish/hall-of-fame")
    @commish_only
    def commish_hall_of_fame():
        record = this_year()
        if record is None:
            flash(f"{year} is not final yet, so nothing was saved.")
        else:
            save_hall_year(hall_path, record)
            flash(f"{year} is saved to the hall of fame: {record['winner']} won.")
        return redirect(url_for("hall_of_fame"))

    @app.route("/commish")
    @commish_only
    def commish():
        members = g.db.execute(
            "SELECT u.id, u.name, u.unlocked, p.user_id IS NOT NULL AS submitted "
            "FROM users u LEFT JOIN picks p ON p.user_id = u.id ORDER BY u.name"
        ).fetchall()
        return render_template("commish.html", members=members, revealed=revealed())

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
        record_edits(user_id, [("reopened the team for one more change", [])])
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

    @app.route("/commish/team/<int:user_id>", methods=["GET", "POST"])
    @commish_only
    def commish_team(user_id):
        member = member_or_404(user_id)
        if not revealed():
            flash("Teams stay hidden until they lock. Until then each person changes their own.")
            return redirect(url_for("commish"))
        before = load_slots(user_id) or {}
        chosen, status = before, 200
        if request.method == "POST":
            after, error = validate_picks(request.form, players, allow_empty=True)
            if error:
                flash(error)
                chosen, status = request.form, 400
            else:
                notes = edit_notes(before, after, players)
                if notes:
                    g.db.execute(
                        "INSERT INTO picks (user_id, slots, submitted_at) VALUES (?, ?, ?) "
                        "ON CONFLICT(user_id) DO UPDATE SET slots = excluded.slots",
                        (user_id, json.dumps(after), now().isoformat()),
                    )
                    record_edits(user_id, notes)
                    g.db.commit()
                flash(f"{member['name']}'s team is changed." if notes else "Nothing was changed.")
                return redirect(url_for("commish_team", user_id=user_id))
        page = render_template(
            "commish_team.html",
            member=member,
            chosen=chosen,
            slots=SLOTS,
            options=options,
            edits=load_edits().get(user_id, []),
        )
        return page, status

    @app.post("/commish/delete/<int:user_id>")
    @commish_only
    def commish_delete(user_id):
        member = member_or_404(user_id)
        if member["id"] == g.user["id"]:
            flash("You cannot delete your own team.")
        elif request.form.get("name") != member["name"]:
            # SQLite hands a deleted last row's id to the next new person, so an old page can name the wrong one.
            flash("That list was out of date, so nothing was deleted. Try again.")
        else:
            for table in USER_TABLES:
                g.db.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
            g.db.execute("DELETE FROM users WHERE id = ?", (user_id,))
            g.db.commit()
            flash(f"{member['name']} and their team are deleted.")
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


def lock_command(args):
    if not POOL_PATH.exists():
        raise SystemExit("No player pool yet. Run: python pickem.py init")
    try:
        aware = parse_time(args.at).tzinfo is not None
    except ValueError:
        aware = False
    if not aware:
        raise SystemExit(f"'{args.at}' is not a time with a zone. Use UTC like 2026-11-26T18:11Z.")
    pool = json.loads(POOL_PATH.read_text(encoding="utf-8"))
    pool[args.key] = args.at
    POOL_PATH.write_text(json.dumps(pool, indent=1), encoding="utf-8")
    print(f"{args.key} set to {args.at}. Restart serve to apply it.")


def lines_command(args):
    if not POOL_PATH.exists():
        raise SystemExit("No player pool yet. Run: python pickem.py init")
    pool = json.loads(POOL_PATH.read_text(encoding="utf-8"))
    for game in pool["games"]:
        # A line already set is kept, so it cannot move under picks already made.
        if game.get("over_under") is None:
            line = espn.parse_over_under(espn.fetch_json(f"summary?event={game['id']}"))
            if line is not None:
                game["over_under"] = line
        print(f"  {game['short']}  over/under {game.get('over_under', 'not listed')}")
    POOL_PATH.write_text(json.dumps(pool, indent=1), encoding="utf-8")
    print("Restart serve to show them.")


def serve_command(args):
    from waitress import serve

    if not POOL_PATH.exists():
        raise SystemExit("No player pool yet. Run: python pickem.py init")
    if not SECRET_PATH.exists():
        SECRET_PATH.write_text(secrets.token_hex(32), encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    version = app_version()
    app = create_app(
        DB_PATH,
        json.loads(POOL_PATH.read_text(encoding="utf-8")),
        secret_key=SECRET_PATH.read_text(encoding="utf-8").strip(),
        version=version,
    )
    print(f"Pick'em version {version} running at http://{args.host}:{args.port}")
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
    lock = commands.add_parser("lock", help="lock and show every team at a set time instead of first kickoff")
    lock.add_argument("at", help="UTC time such as 2026-11-26T18:11Z")
    lock.set_defaults(run=lock_command, key="lock_at")
    lock_picks = commands.add_parser("lock-picks", help="lock and show the game picks at a set time instead of with the teams")
    lock_picks.add_argument("at", help="UTC time such as 2026-11-26T19:00Z")
    lock_picks.set_defaults(run=lock_command, key="picks_lock_at")
    lines = commands.add_parser("lines", help="load each game's over/under line from ESPN for the game pick'em")
    lines.set_defaults(run=lines_command)
    serve = commands.add_parser("serve", help="run the web app")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", default=8080, type=int)
    serve.set_defaults(run=serve_command)
    args = parser.parse_args()
    args.run(args)


if __name__ == "__main__":
    main()
