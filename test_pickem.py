from datetime import datetime, timezone

import pytest

import espn
import pickem

BEFORE_KICKOFF = datetime(2026, 11, 26, 17, 0, tzinfo=timezone.utc)
AFTER_KICKOFF = datetime(2026, 11, 26, 18, 30, tzinfo=timezone.utc)


def player(player_id, name, position, team):
    return {"id": player_id, "name": name, "pos": position, "team": team}


POOL = {
    "date": "20261126",
    "games": [
        {
            "id": "g1",
            "kickoff": "2026-11-26T18:00Z",
            "short": "CHI @ DET",
            "teams": [
                {"id": "3", "abbr": "CHI", "name": "Chicago Bears"},
                {"id": "8", "abbr": "DET", "name": "Detroit Lions"},
            ],
        }
    ],
    "players": [
        player("q1", "Quinn Passer", "QB", "DET"),
        player("q2", "Other Thrower", "QB", "CHI"),
        player("r1", "Rory Runner", "RB", "DET"),
        player("r2", "Ray Rusher", "RB", "CHI"),
        player("w1", "Wes Wideout", "WR", "DET"),
        player("w2", "Walt Catcher", "WR", "CHI"),
        player("t1", "Ty Tightend", "TE", "DET"),
        player("k1", "Kip Kicker", "K", "DET"),
        player("DEF-DET", "Detroit Lions", "DEF", "DET"),
        player("DEF-CHI", "Chicago Bears", "DEF", "CHI"),
    ],
}
ROSTER = {"QB": "q1", "RB1": "r1", "RB2": "r2", "WR1": "w1", "WR2": "w2", "TE": "t1", "DEF": "DEF-DET", "K": "k1"}


def stat_line(player_id, stats):
    return {"athlete": {"id": player_id}, "stats": stats}


# Shaped like ESPN's summary endpoint: category keys and string values as it returns them.
SUMMARY = {
    "header": {
        "competitions": [
            {
                "status": {"type": {"state": "in", "shortDetail": "5:32 - 2nd"}},
                "competitors": [
                    {"team": {"abbreviation": "DET"}, "score": "24"},
                    {"team": {"abbreviation": "CHI"}, "score": "10"},
                ],
            }
        ]
    },
    "boxscore": {
        "teams": [
            {"team": {"abbreviation": "DET"}, "statistics": [{"name": "defensiveTouchdowns", "displayValue": "1"}]},
            {
                "team": {"abbreviation": "CHI"},
                "statistics": [
                    {"name": "sacksYardsLost", "displayValue": "3-20"},
                    {"name": "interceptions", "displayValue": "1"},
                    {"name": "fumblesLost", "displayValue": "1"},
                ],
            },
        ],
        "players": [
            {
                "team": {"abbreviation": "DET"},
                "statistics": [
                    {
                        "name": "passing",
                        "keys": ["completions/passingAttempts", "passingYards", "passingTouchdowns", "interceptions"],
                        "athletes": [stat_line("q1", ["20/30", "250", "2", "1"])],
                    },
                    {
                        "name": "rushing",
                        "keys": ["rushingAttempts", "rushingYards", "rushingTouchdowns"],
                        "athletes": [stat_line("r1", ["15", "80", "1"]), stat_line("q1", ["3", "10", "0"])],
                    },
                    {
                        "name": "receiving",
                        "keys": ["receptions", "receivingYards", "receivingTouchdowns"],
                        "athletes": [stat_line("w1", ["5", "70", "1"]), stat_line("r1", ["2", "15", "0"])],
                    },
                    {"name": "fumbles", "keys": ["fumbles", "fumblesLost"], "athletes": [stat_line("r1", ["1", "1"])]},
                    {
                        "name": "kicking",
                        "keys": ["fieldGoalsMade/fieldGoalAttempts", "totalKickingPoints"],
                        "athletes": [stat_line("k1", ["1/1", "6"])],
                    },
                ],
            }
        ],
    },
}


@pytest.fixture
def clock():
    return {"now": BEFORE_KICKOFF}


@pytest.fixture
def app(tmp_path, clock):
    db_path = tmp_path / "pickem.db"
    application = pickem.create_app(
        db_path, POOL, now=lambda: clock["now"], fetch=lambda path: SUMMARY, secret_key="test"
    )
    db = pickem.connect(db_path)
    for name in ("Shane", "Jill", "Papaw"):
        pickem.add_user(db, name)
    db.execute("UPDATE users SET is_commish = 1 WHERE name = 'Shane'")
    db.commit()
    db.close()
    return application


def post(client, path, **form):
    client.get("/login", follow_redirects=True)
    with client.session_transaction() as browser_session:
        form["csrf"] = browser_session["csrf"]
    return client.post(path, data=form, follow_redirects=True)


def join(app, name, password="gobble26"):
    """Log in with the starter password and replace it, as each person does on first visit."""
    client = app.test_client()
    post(client, "/login", name=name, password=name)
    post(client, "/account", name=name, password=password, confirm=password)
    return client


def page(client, path):
    return client.get(path, follow_redirects=True).get_data(as_text=True)


def test_starter_password_is_the_name_and_must_be_replaced(app):
    client = app.test_client()
    landing = post(client, "/login", name="papaw", password=" Papaw ").get_data(as_text=True)
    assert "Choose your name and password" in landing
    assert client.get("/").headers["Location"].endswith("/account")

    refused = post(client, "/account", name="Papaw", password="papaw", confirm="papaw").get_data(as_text=True)
    assert "not your name" in refused

    post(client, "/account", name="Papaw", password="stuffing", confirm="stuffing")
    assert "Choose a QB" in page(client, "/")

    fresh = app.test_client()
    assert "do not match" in post(fresh, "/login", name="Papaw", password="Papaw").get_data(as_text=True)
    assert "My team" in post(fresh, "/login", name="Papaw", password="stuffing").get_data(as_text=True)


def test_a_new_name_starts_a_team_until_kickoff(app, clock):
    newcomer = app.test_client()
    assert "do not match" in post(newcomer, "/login", name="Grandma", password="wrong").get_data(as_text=True)
    landing = post(newcomer, "/login", name="Grandma", password="grandma ").get_data(as_text=True)
    assert "Choose your name and password" in landing

    clock["now"] = AFTER_KICKOFF
    late = post(app.test_client(), "/login", name="Cousin", password="Cousin").get_data(as_text=True)
    assert "New teams closed at kickoff" in late
    board = page(join(app, "Jill"), "/teams")
    assert "Grandma" in board and "Cousin" not in board


def test_a_team_can_be_changed_until_kickoff_and_then_locks(app, clock):
    jill = join(app, "Jill")
    post(jill, "/picks", **ROSTER)
    changed = post(jill, "/picks", **{**ROSTER, "QB": "q2"}).get_data(as_text=True)

    assert "Your team is saved" in changed
    assert 'value="q2" selected' in changed

    clock["now"] = AFTER_KICKOFF
    late = post(jill, "/picks", **ROSTER).get_data(as_text=True)

    assert "Your team is locked" in late
    assert "Other Thrower" in late
    assert "Quinn Passer" not in late


def test_only_the_commish_can_reopen_a_team_and_it_locks_again(app, clock):
    jill = join(app, "Jill")
    shane = join(app, "Shane")
    post(jill, "/picks", **ROSTER)
    jill_id = 2
    clock["now"] = AFTER_KICKOFF

    assert post(jill, f"/commish/unlock/{jill_id}").status_code == 403

    post(shane, f"/commish/unlock/{jill_id}")
    changed = post(jill, "/picks", **{**ROSTER, "QB": "q2"}).get_data(as_text=True)
    assert "Other Thrower" in changed
    assert "Your team is locked" in post(jill, "/picks", **ROSTER).get_data(as_text=True)


def test_other_teams_are_hidden_until_first_kickoff(app, clock):
    jill = join(app, "Jill")
    papaw = join(app, "Papaw")
    post(jill, "/picks", **ROSTER)

    hidden = page(papaw, "/teams")
    assert "Jill" in hidden and "Submitted" in hidden
    assert "Quinn Passer" not in hidden

    clock["now"] = AFTER_KICKOFF
    assert "Quinn Passer" in page(papaw, "/teams")


@pytest.mark.parametrize(
    "change, complaint",
    [
        ({"RB2": "r1"}, "on your team twice"),
        ({"QB": "r2"}, "Choose a player for QB"),
        ({"TE": ""}, "Choose a player for TE"),
        ({"K": "nobody"}, "Choose a player for K"),
    ],
)
def test_an_invalid_roster_is_refused_and_nothing_is_saved(app, change, complaint):
    jill = join(app, "Jill")
    refused = post(jill, "/picks", **{**ROSTER, **change})

    assert refused.status_code == 400
    assert complaint in refused.get_data(as_text=True)
    mine = page(jill, "/")
    assert "Save my team" in mine
    assert "Your team is saved" not in mine


def test_no_team_can_be_entered_after_kickoff_without_the_commish(app, clock):
    jill = join(app, "Jill")
    clock["now"] = AFTER_KICKOFF

    assert "Your team is locked" in post(jill, "/picks", **ROSTER).get_data(as_text=True)
    assert "Ask the commish" in page(jill, "/")


def test_fantasy_points_from_a_box_score():
    result = espn.parse_fantasy_points(SUMMARY)

    assert result["detail"] == "5:32 - 2nd"
    assert result["points"] == {
        "q1": 17.0,  # 250 yd * 0.04 + 2 TD * 4 - 1 INT * 2, plus 10 rush yd
        "r1": 15.5,  # 80 rush yd + TD, 2 catches for 15, lost fumble
        "w1": 18.0,  # 5 catches, 70 yd, TD
        "k1": 6.0,
        "DEF-DET": 17.0,  # 3 sacks, INT, fumble recovery, TD, 10 points allowed
        "DEF-CHI": 0.0,  # 24 points allowed
    }


def test_no_points_before_a_game_kicks_off():
    pregame = {"header": {"competitions": [{"status": {"type": {"state": "pre"}}, "competitors": []}]}}

    assert espn.parse_fantasy_points(pregame)["points"] == {}


def test_leaderboard_ranks_teams_by_live_points(app, clock):
    jill = join(app, "Jill")
    papaw = join(app, "Papaw")
    post(jill, "/picks", **ROSTER)
    post(papaw, "/picks", **{**ROSTER, "QB": "q2", "DEF": "DEF-CHI"})
    clock["now"] = AFTER_KICKOFF

    board = page(papaw, "/teams")

    assert "73.50" in board  # Jill: 17 + 15.5 + 0 + 18 + 0 + 0 + 17 + 6
    assert "39.50" in board  # Papaw: same roster without q1 and the DET defense
    assert "1. Jill" in board and "2. Papaw" in board and "3. Shane" in board
    assert "No team submitted" in board


def test_roster_keeps_fantasy_positions_from_the_active_roster():
    def athlete(player_id, position):
        return {"id": player_id, "displayName": f"Player {player_id}", "position": {"abbreviation": position}}

    roster = {
        "team": {"abbreviation": "DET"},
        "athletes": [
            {"position": "offense", "items": [athlete("1", "QB"), athlete("2", "OT"), athlete("3", "FB")]},
            {"position": "defense", "items": [athlete("4", "LB")]},
            {"position": "specialTeam", "items": [athlete("5", "PK"), athlete("6", "P")]},
            {"position": "injuredReserveOrOut", "items": [athlete("7", "WR")]},
            {"position": "practiceSquad", "items": [athlete("8", "TE")]},
        ],
    }

    assert [(p["id"], p["pos"]) for p in espn.parse_roster(roster)] == [("1", "QB"), ("3", "RB"), ("5", "K")]
