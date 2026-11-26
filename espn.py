"""ESPN's public NFL API as the pick'em's data boundary: games, rosters, live fantasy points.

The endpoints are unofficial and unauthenticated. Every parse_* function takes
decoded JSON so the scoring rules can be tested without the network.

Not scored, because the box score does not carry them: two-point conversions,
safeties, blocked kicks and field-goal distance bonuses.
"""
import json
import urllib.request

BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/"

FANTASY_URL = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/"
# ESPN's standard full-PPR scoring. A private league's own scoring needs that league's login.
FANTASY_SCORING = "leaguedefaults/3"
FANTASY_SLOTS = [0, 2, 4, 6, 16, 17]  # QB, RB, WR, TE, D/ST, K
PROJECTED = 1  # statSourceId; 0 is actual
ONE_WEEK = 1  # statSplitTypeId; 0 is the whole season

ROSTER_POSITIONS = {"QB": "QB", "RB": "RB", "FB": "RB", "WR": "WR", "TE": "TE", "PK": "K"}
ROSTER_GROUPS = ("offense", "specialTeam")

# (box-score category, stat key) -> fantasy points per unit. Full-point PPR.
PLAYER_POINTS = {
    ("passing", "passingYards"): 0.04,
    ("passing", "passingTouchdowns"): 4,
    ("passing", "interceptions"): -2,
    ("rushing", "rushingYards"): 0.1,
    ("rushing", "rushingTouchdowns"): 6,
    ("receiving", "receptions"): 1,
    ("receiving", "receivingYards"): 0.1,
    ("receiving", "receivingTouchdowns"): 6,
    ("fumbles", "fumblesLost"): -2,
    ("kickReturns", "kickReturnTouchdowns"): 6,
    ("puntReturns", "puntReturnTouchdowns"): 6,
    ("kicking", "totalKickingPoints"): 1,
}
DEFENSE_POINTS = {"sack": 1, "interception": 2, "fumble_recovery": 2, "touchdown": 6}
# (most points allowed, bonus), checked in order; anything above the last tier gets the floor.
POINTS_ALLOWED_TIERS = ((0, 10), (6, 7), (13, 4), (20, 1), (27, 0), (34, -1))
POINTS_ALLOWED_FLOOR = -4


def fetch_json(path):
    request = urllib.request.Request(BASE_URL + path, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=8) as response:
        return json.load(response)


def defense_id(abbr):
    return f"DEF-{abbr}"


def parse_games(scoreboard):
    games = []
    for event in scoreboard.get("events", []):
        competitors = event["competitions"][0]["competitors"]
        games.append(
            {
                "id": event["id"],
                "kickoff": event["date"],
                "short": event["shortName"],
                "teams": [
                    {
                        "id": c["team"]["id"],
                        "abbr": c["team"]["abbreviation"],
                        "name": c["team"]["displayName"],
                    }
                    for c in competitors
                ],
            }
        )
    return sorted(games, key=lambda game: game["kickoff"])


def parse_roster(roster):
    abbr = roster["team"]["abbreviation"]
    players = []
    for group in roster.get("athletes", []):
        if group.get("position") not in ROSTER_GROUPS:
            continue
        for athlete in group.get("items", []):
            position = ROSTER_POSITIONS.get(athlete["position"]["abbreviation"])
            if position:
                players.append(
                    {"id": athlete["id"], "name": athlete["displayName"], "pos": position, "team": abbr}
                )
    return players


def build_pool(date, fetch=fetch_json):
    games = parse_games(fetch(f"scoreboard?dates={date}"))
    players = []
    for game in games:
        for team in game["teams"]:
            players.extend(parse_roster(fetch(f"teams/{team['id']}/roster")))
            players.append(
                {"id": defense_id(team["abbr"]), "name": team["name"], "pos": "DEF", "team": team["abbr"]}
            )
    return {"date": date, "games": games, "players": players}


def fetch_fantasy_json(path, filters=None):
    headers = {"User-Agent": "Mozilla/5.0"}
    if filters:
        headers["x-fantasy-filter"] = json.dumps(filters)
    request = urllib.request.Request(FANTASY_URL + path, headers=headers)
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


def parse_projections(payload, week, abbr_by_team_id):
    """Projected points for one week, keyed like the pool: athlete id, or DEF-<abbr> for a D/ST."""
    projections = {}
    for entry in payload.get("players", []):
        player = entry["player"]
        for stat in player.get("stats", []):
            if (stat.get("statSourceId"), stat.get("statSplitTypeId"), stat.get("scoringPeriodId")) != (
                PROJECTED,
                ONE_WEEK,
                week,
            ):
                continue
            abbr = abbr_by_team_id.get(str(player.get("proTeamId")))
            player_id = defense_id(abbr) if entry["id"] < 0 and abbr else str(entry["id"])
            projections[player_id] = round(stat.get("appliedTotal", 0), 1)
    return projections


def add_projections(pool, fetch=fetch_fantasy_json):
    """Set each pool player's "proj" to ESPN's projection for the current week; None when ESPN has none."""
    year, month = int(pool["date"][:4]), int(pool["date"][4:6])
    season = year if month >= 3 else year - 1
    week = fetch(f"{season}?view=kona_game_state")["currentScoringPeriod"]["id"]
    teams = {team["id"]: team["abbr"] for game in pool["games"] for team in game["teams"]}
    filters = {
        "players": {
            "filterSlotIds": {"value": FANTASY_SLOTS},
            "filterProTeamIds": {"value": [int(team_id) for team_id in teams]},
            "filterStatsForCurrentSeasonScoringPeriodId": {"value": [week]},
            "limit": 100 * len(teams),
            "sortPercOwned": {"sortPriority": 1, "sortAsc": False},
        }
    }
    payload = fetch(f"{season}/segments/0/{FANTASY_SCORING}?view=kona_player_info", filters)
    projections = parse_projections(payload, week, teams)
    for player in pool["players"]:
        player["proj"] = projections.get(player["id"])
    return week


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def defense_points(own_stats, opponent_stats, points_allowed):
    sacks = _number(str(opponent_stats.get("sacksYardsLost", "0")).split("-")[0])
    earned = (
        sacks * DEFENSE_POINTS["sack"]
        + _number(opponent_stats.get("interceptions")) * DEFENSE_POINTS["interception"]
        + _number(opponent_stats.get("fumblesLost")) * DEFENSE_POINTS["fumble_recovery"]
        + _number(own_stats.get("defensiveTouchdowns")) * DEFENSE_POINTS["touchdown"]
    )
    bonus = next(
        (bonus for limit, bonus in POINTS_ALLOWED_TIERS if points_allowed <= limit),
        POINTS_ALLOWED_FLOOR,
    )
    return round(earned + bonus, 2)


def parse_over_under(summary):
    """The total-points line from the first sportsbook ESPN lists for the game, or None."""
    for entry in summary.get("pickcenter") or []:
        if entry.get("overUnder") is not None:
            return float(entry["overUnder"])
    return None


def parse_fantasy_points(summary):
    """Return {"state", "detail", "points", "scores", "winner"} for one game.

    Points and scores stay empty until kickoff. The winner stays None until the
    game is final, and after a tie.
    """
    competition = summary["header"]["competitions"][0]
    status = competition["status"]["type"]
    result = {
        "state": status["state"],
        "detail": status.get("shortDetail") or status.get("description") or status["state"],
        "points": {},
        "scores": {},
        "winner": None,
    }
    if status["state"] == "pre":
        return result

    points = result["points"]
    boxscore = summary.get("boxscore", {})
    for team in boxscore.get("players", []):
        for category in team.get("statistics", []):
            for line in category.get("athletes", []):
                earned = sum(
                    _number(value) * PLAYER_POINTS.get((category["name"], key), 0)
                    for key, value in zip(category["keys"], line["stats"])
                )
                if earned:
                    player_id = line["athlete"]["id"]
                    points[player_id] = round(points.get(player_id, 0) + earned, 2)

    scores = {c["team"]["abbreviation"]: _number(c.get("score")) for c in competition["competitors"]}
    team_stats = {
        team["team"]["abbreviation"]: {s["name"]: s["displayValue"] for s in team.get("statistics", [])}
        for team in boxscore.get("teams", [])
    }
    for abbr in scores:
        opponent = next(other for other in scores if other != abbr)
        points[defense_id(abbr)] = defense_points(
            team_stats.get(abbr, {}), team_stats.get(opponent, {}), scores[opponent]
        )
    result["scores"] = {abbr: int(score) for abbr, score in scores.items()}
    if status["state"] == "post":
        best = max(scores.values())
        leaders = [abbr for abbr, score in scores.items() if score == best]
        result["winner"] = leaders[0] if len(leaders) == 1 else None
    return result
