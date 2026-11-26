import json
import re
import subprocess
from datetime import datetime, timezone

import pytest

import espn
import pickem

BEFORE_KICKOFF = datetime(2026, 11, 26, 17, 0, tzinfo=timezone.utc)
AFTER_KICKOFF = datetime(2026, 11, 26, 18, 30, tzinfo=timezone.utc)
AFTER_LAST_GAME = datetime(2026, 11, 27, 5, 0, tzinfo=timezone.utc)


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
        player("t2", "Tad Flexer", "TE", "CHI"),
        player("k1", "Kip Kicker", "K", "DET"),
        player("DEF-DET", "Detroit Lions", "DEF", "DET"),
        player("DEF-CHI", "Chicago Bears", "DEF", "CHI"),
    ],
}
ROSTER = {
    "QB": "q1",
    "RB1": "r1",
    "RB2": "r2",
    "WR1": "w1",
    "WR2": "w2",
    "TE": "t1",
    "FLEX": "t2",
    "DEF": "DEF-DET",
    "K": "k1",
}
TWO_GAMES = {
    **POOL,
    "games": [
        *POOL["games"],
        {
            "id": "g2",
            "kickoff": "2026-11-27T01:20Z",
            "short": "KC @ BUF",
            "teams": [
                {"id": "12", "abbr": "KC", "name": "Kansas City Chiefs"},
                {"id": "2", "abbr": "BUF", "name": "Buffalo Bills"},
            ],
        },
    ],
    "players": [*POOL["players"], player("b1", "Bo Backup", "RB", "BUF")],
}
FINAL = {
    "header": {
        "competitions": [
            {
                "status": {"type": {"state": "post", "shortDetail": "Final"}},
                "competitors": [
                    {"team": {"abbreviation": "BUF"}, "score": "28"},
                    {"team": {"abbreviation": "KC"}, "score": "21"},
                ],
            }
        ]
    }
}


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


def join(app, name):
    client = app.test_client()
    post(client, "/login", name=name)
    return client


def page(client, path):
    return client.get(path, follow_redirects=True).get_data(as_text=True)


def test_a_name_alone_opens_that_persons_team(app):
    client = app.test_client()
    landing = post(client, "/login", name=" papaw ").get_data(as_text=True)
    assert "Save my team" in landing
    post(client, "/picks", **ROSTER)

    again = post(app.test_client(), "/login", name="PAPAW").get_data(as_text=True)
    assert f'value="{ROSTER["QB"]}" selected' in again


def test_a_new_name_starts_a_team_until_kickoff(app, clock):
    landing = post(app.test_client(), "/login", name="Grandma").get_data(as_text=True)
    assert "Save my team" in landing

    clock["now"] = AFTER_KICKOFF
    late = post(app.test_client(), "/login", name="Cousin").get_data(as_text=True)
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


def test_projections_are_keyed_like_the_pool():
    def stat(week, total, source=1):
        return {"statSourceId": source, "statSplitTypeId": 1, "scoringPeriodId": week, "appliedTotal": total}

    payload = {
        "players": [
            {"id": 101, "player": {"proTeamId": 8, "stats": [stat(11, 9.0), stat(12, 30.0, source=0), stat(12, 21.44)]}},
            {"id": -16008, "player": {"proTeamId": 8, "stats": [stat(12, 6.72)]}},
        ]
    }

    assert espn.parse_projections(payload, 12, {"8": "DET"}) == {"101": 21.4, "DEF-DET": 6.7}


def test_the_picker_lists_players_best_projection_first(tmp_path, clock):
    projected = {"q2": 21.4, "q1": 9.0}
    pool = {**POOL, "players": [{**p, "proj": projected.get(p["id"])} for p in POOL["players"]]}
    application = pickem.create_app(
        tmp_path / "pickem.db", pool, now=lambda: clock["now"], fetch=lambda path: SUMMARY, secret_key="test"
    )

    mine = page(join(application, "Jill"), "/")

    assert mine.index("Other Thrower (CHI) 21.4") < mine.index("Quinn Passer (DET) 9.0")
    assert "Rory Runner (DET)<" in mine


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


def two_game_app(tmp_path, clock):
    return pickem.create_app(
        tmp_path / "pickem.db",
        TWO_GAMES,
        now=lambda: clock["now"],
        fetch=lambda path: FINAL if "g2" in path else SUMMARY,
        secret_key="test",
    )


def test_a_lock_time_in_the_pool_replaces_first_kickoff(tmp_path, clock):
    application = pickem.create_app(
        tmp_path / "pickem.db",
        {**POOL, "lock_at": "2026-11-26T18:11Z"},
        now=lambda: clock["now"],
        fetch=lambda path: SUMMARY,
        secret_key="test",
    )
    jill = join(application, "Jill")

    clock["now"] = datetime(2026, 11, 26, 18, 5, tzinfo=timezone.utc)
    assert "Your team is saved" in post(jill, "/picks", **ROSTER).get_data(as_text=True)

    clock["now"] = datetime(2026, 11, 26, 18, 12, tzinfo=timezone.utc)
    assert "Your team is locked" in post(jill, "/picks", **ROSTER).get_data(as_text=True)


def test_a_locked_team_saved_without_a_flex_adds_one_from_a_game_not_kicked_off(tmp_path, clock):
    application = two_game_app(tmp_path, clock)
    jill = join(application, "Jill")
    post(jill, "/picks", **ROSTER)
    # A team saved before the flex spot existed.
    db = pickem.connect(tmp_path / "pickem.db")
    db.execute("UPDATE picks SET slots = ?", (json.dumps({k: v for k, v in ROSTER.items() if k != "FLEX"}),))
    db.commit()
    db.close()
    clock["now"] = AFTER_KICKOFF

    mine = page(jill, "/")
    assert "Bo Backup (BUF RB)" in mine
    assert "Tad Flexer" not in mine  # his game has kicked off

    assert "Not picked" in post(jill, "/flex", FLEX="t2").get_data(as_text=True)

    saved = post(jill, "/flex", FLEX="b1").get_data(as_text=True)
    assert "Bo Backup is your flex" in saved
    assert "Add your flex" not in saved


def test_equal_totals_are_ordered_by_the_tiebreaker_once_the_last_game_ends(tmp_path, clock):
    application = two_game_app(tmp_path, clock)
    amy, bob, zed = join(application, "Amy"), join(application, "Bob"), join(application, "Zed")
    for client in (amy, bob, zed):
        post(client, "/picks", **ROSTER)
    assert "Choose who wins" in post(amy, "/tiebreaker", winner="DET", total="49").get_data(as_text=True)
    post(amy, "/tiebreaker", winner="KC", total="49")  # exact total, wrong winner
    post(zed, "/tiebreaker", winner="BUF", total="60")  # right winner, 11 off
    post(bob, "/tiebreaker", winner="BUF", total="45")  # right winner, 4 off

    clock["now"] = AFTER_KICKOFF
    early = page(amy, "/teams")
    assert "1. Amy" in early and "2. Bob" in early and "3. Zed" in early
    assert "Tiebreaker:" not in early

    clock["now"] = AFTER_LAST_GAME
    board = page(amy, "/teams")
    assert "1. Bob" in board and "2. Zed" in board and "3. Amy" in board
    assert "Tiebreaker: KC wins KC @ BUF, total score 49" in board
    assert "locked when" in post(amy, "/tiebreaker", winner="BUF", total="49").get_data(as_text=True)


def test_game_picks_are_scored_apart_from_fantasy_and_hidden_until_they_lock(tmp_path, clock):
    application = pickem.create_app(
        tmp_path / "pickem.db",
        {**TWO_GAMES, "picks_lock_at": "2026-11-26T19:00Z"},
        now=lambda: clock["now"],
        fetch=lambda path: FINAL if "g2" in path else SUMMARY,
        secret_key="test",
    )
    amy, bob, zed = join(application, "Amy"), join(application, "Bob"), join(application, "Zed")
    clock["now"] = AFTER_KICKOFF  # teams are locked; game picks are still open

    refused = post(amy, "/game-picks", **{"pick-g1": "BUF"}).get_data(as_text=True)
    assert "Choose a team playing in CHI @ DET" in refused
    post(amy, "/game-picks", **{"pick-g1": "DET", "pick-g2": "BUF"})
    post(bob, "/game-picks", **{"pick-g2": "KC"})
    hidden = page(zed, "/teams").split("Game pick'em")[1]
    assert "Amy" not in hidden and "Game picks show at" in hidden

    clock["now"] = AFTER_LAST_GAME
    assert "game picks are locked" in post(bob, "/game-picks", **{"pick-g2": "BUF"}).get_data(as_text=True)
    standings = page(zed, "/teams").split("Game pick'em")[1]
    assert standings.index("Amy") < standings.index("Bob")
    assert "DET</td>" in standings  # CHI @ DET is not final, so that pick is unmarked
    assert "BUF ✓" in standings and "KC ✗" in standings
    assert "Zed" not in standings


def test_over_under_picks_count_in_the_game_pickem(tmp_path, clock):
    lined = [{**game, "over_under": 45.5} if game["id"] == "g2" else game for game in TWO_GAMES["games"]]
    application = pickem.create_app(
        tmp_path / "pickem.db",
        {**TWO_GAMES, "games": lined},
        now=lambda: clock["now"],
        fetch=lambda path: FINAL if "g2" in path else SUMMARY,
        secret_key="test",
    )
    amy, bob = join(application, "Amy"), join(application, "Bob")

    assert "Choose over or under for KC @ BUF" in post(amy, "/game-picks", **{"ou-g2": "push"}).get_data(as_text=True)
    assert "Choose over or under for CHI @ DET" in post(amy, "/game-picks", **{"ou-g1": "over"}).get_data(as_text=True)
    post(amy, "/game-picks", **{"pick-g2": "KC", "ou-g2": "over"})
    post(bob, "/game-picks", **{"pick-g2": "KC", "ou-g2": "under"})

    clock["now"] = AFTER_LAST_GAME  # BUF 28, KC 21: 49 points, over the 45.5 line
    standings = page(amy, "/teams").split("Game pick'em")[1]
    assert "O/U 45.5" in standings
    assert "Over ✓" in standings and "Under ✗" in standings
    assert standings.index("Amy") < standings.index("Bob")
    assert "Over 45.5 ✓" in page(amy, "/")


def test_the_over_under_line_comes_from_the_first_sportsbook_listed():
    assert espn.parse_over_under({"pickcenter": [{"details": "BUF -3"}, {"overUnder": 45.5}]}) == 45.5
    assert espn.parse_over_under({}) is None


def test_the_commish_changes_a_locked_roster_and_the_change_is_called_out(app, clock):
    jill, shane = join(app, "Jill"), join(app, "Shane")
    post(jill, "/picks", **ROSTER)
    jill_id = 2
    changed = {**ROSTER, "QB": "q2", "K": ""}

    early = post(shane, f"/commish/team/{jill_id}", **changed).get_data(as_text=True)
    assert "Teams stay hidden until they lock" in early

    clock["now"] = AFTER_KICKOFF
    assert post(jill, f"/commish/team/{jill_id}", **changed).status_code == 403
    assert post(shane, f"/commish/team/{jill_id}", **{**ROSTER, "RB2": "r1"}).status_code == 400
    assert "Edited by commish" not in page(jill, "/")

    post(shane, f"/commish/team/{jill_id}", **changed)

    for seen in (page(jill, "/"), page(join(app, "Papaw"), "/teams")):
        assert "Edited by commish at <time" in seen
        assert "added Other Thrower at QB, replacing Quinn Passer." in seen
        assert "removed Kip Kicker from K." in seen
    assert "50.50" in page(jill, "/teams")  # 73.50 without q1's 17 and k1's 6; q2 has no points yet


def test_a_change_to_a_reopened_team_after_the_lock_is_called_out(app, clock):
    jill, shane = join(app, "Jill"), join(app, "Shane")
    post(jill, "/picks", **ROSTER)
    clock["now"] = AFTER_KICKOFF

    post(shane, "/commish/unlock/2")
    post(jill, "/picks", **{**ROSTER, "QB": "q2"})

    board = page(join(app, "Papaw"), "/teams")
    assert "Edited by commish at <time" in board
    assert "reopened the team for one more change." in board
    assert "approved a change after reopening the team: added Other Thrower at QB, replacing Quinn Passer." in board


def test_a_refused_save_says_why(app, clock):
    jill = join(app, "Jill")
    clock["now"] = AFTER_KICKOFF

    not_commish = post(jill, "/commish/team/2", **ROSTER)
    assert not_commish.status_code == 403
    assert "this browser is logged in as Jill" in not_commish.get_data(as_text=True)

    stale = join(app, "Shane").post("/commish/team/2", data={**ROSTER, "csrf": "from an older page"})
    assert stale.status_code == 400
    assert "out of date, so nothing was saved" in stale.get_data(as_text=True)


def test_every_page_shows_the_version_it_was_started_with(tmp_path, clock):
    application = pickem.create_app(
        tmp_path / "pickem.db", POOL, now=lambda: clock["now"], secret_key="test", version="1.7 (abc1234)"
    )

    assert "Version 1.7 (abc1234)" in page(application.test_client(), "/login")


def test_the_version_is_read_from_git_and_changes_with_each_commit(tmp_path):
    def git(*args):
        identity = ("-c", "user.name=Test", "-c", "user.email=test@example.com", "-c", "commit.gpgsign=false")
        subprocess.run(["git", *identity, *args], cwd=tmp_path, check=True, capture_output=True)

    assert pickem.app_version(tmp_path) == "unversioned"

    git("init", "-q")
    (tmp_path / "notes.txt").write_text("one", encoding="utf-8")
    git("add", ".")
    git("commit", "-q", "-m", "one")
    first = pickem.app_version(tmp_path)
    assert re.fullmatch(r"1\.1 \([0-9a-f]{7,}\)", first)

    (tmp_path / "notes.txt").write_text("two", encoding="utf-8")
    assert pickem.app_version(tmp_path).endswith("+changes)")

    git("commit", "-q", "-a", "-m", "two")
    second = pickem.app_version(tmp_path)
    assert second.startswith("1.2 (") and second != first


def test_the_commish_deletes_a_team_only_when_the_name_matches_the_id(app, clock):
    jill, shane = join(app, "Jill"), join(app, "Shane")
    post(jill, "/picks", **ROSTER)
    shane_id, jill_id = 1, 2
    clock["now"] = AFTER_KICKOFF

    assert post(jill, f"/commish/delete/{jill_id}", name="Jill").status_code == 403
    assert "nothing was deleted" in post(shane, f"/commish/delete/{jill_id}", name="Papaw").get_data(as_text=True)
    assert "cannot delete your own" in post(shane, f"/commish/delete/{shane_id}", name="Shane").get_data(as_text=True)
    assert "Quinn Passer" in page(shane, "/teams")

    gone = post(shane, f"/commish/delete/{jill_id}", name="Jill").get_data(as_text=True)
    assert "Jill and their team are deleted" in gone
    board = page(shane, "/teams")
    assert "Jill" not in board and "Quinn Passer" not in board
    assert "Papaw" in board
    assert "Log out" not in page(jill, "/")  # her session no longer opens a team


def test_a_final_game_reports_its_score_and_winner():
    result = espn.parse_fantasy_points(FINAL)

    assert result["scores"] == {"BUF": 28, "KC": 21}
    assert result["winner"] == "BUF"
    assert espn.parse_fantasy_points(SUMMARY)["winner"] is None


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
