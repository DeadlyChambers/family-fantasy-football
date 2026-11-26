# family-fantasy-football

It is pretty simple. Update the scores.ini with the player scores, and set the teams with player and positions. Then when ready run
```
source ~/.vevn/family-fantasy-football/Scripts/activate
python startup.py
deactivate
```

There is another more interesting output if you want to see the individual player scores for a person's team use the verbose flag.
```
python startup.py -v
```

## Thanksgiving pick'em (web)

A small web app where each person picks a QB, 2 RBs, 2 WRs, a TE, a DEF and a K from the day's NFL games.

```
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-pickem.txt
.venv/Scripts/python pickem.py init      # loads today's games and players from ESPN, creates the accounts
.venv/Scripts/python pickem.py serve     # http://127.0.0.1:8080
.venv/Scripts/python -m pytest test_pickem.py
```

- **Accounts:** `init` creates one per `[section]` in teams.ini. The first password is the person's name; the first login makes them choose their own name and password. Until then anyone who knows a name can claim that account.
- **Locking:** submitting a team locks it. The commish (`--commish`, default Shane) can reopen a team, reset a password or add a person on the Commish page. No team can be entered after first kickoff without the commish.
- **Reveal:** nobody sees another person's team until the day's first kickoff. After that the Everyone page is a leaderboard that refreshes about once a minute.
- **Scoring:** full-point PPR from ESPN's box score; the tables are `PLAYER_POINTS`, `DEFENSE_POINTS` and `POINTS_ALLOWED_TIERS` in espn.py. Two-point conversions, safeties, blocked kicks and field-goal distance bonuses are not scored.
- **Other days:** `pickem.py init --date YYYYMMDD` loads a different game day. Delete pickem.db first to start a new contest.

## Notes
The models are in models.py which is mostly the string output methods.
The startup.py is the core code. If you need a major logic change it will be there.

After running if any names or scores show up with yellow, you may need to ensure the player is added to the scores.ini
If there are any red scores, make sure you made them more than 0