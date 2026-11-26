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

A small web app where each person picks a QB, 2 RBs, 2 WRs, a TE, a FLEX (RB, WR or TE), a DEF and a K from the day's NFL games.

```
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-pickem.txt
.venv/Scripts/python pickem.py init      # loads today's games and players from ESPN, creates the accounts
.venv/Scripts/python pickem.py serve     # http://127.0.0.1:8080
.venv/Scripts/python -m pytest test_pickem.py
```

- **Accounts:** there are no passwords. A person types their name and lands on their team; `init` creates one team per `[section]` in teams.ini, and until first kickoff a new name starts a new team. Anyone with the link can therefore open or change another person's team before kickoff, and can act as the commish by typing the commish's name.
- **Locking:** a team can be saved and changed as often as wanted until first kickoff, when every team locks. After that the commish (`--commish`, default Shane) can reopen a team for one more submit. The commish can also add a person on the Commish page. No new team can be started after first kickoff without the commish.
- **Commish changes:** once teams lock, the Commish page has an "Edit team" link per person. Each spot the commish changes is listed on that team, on the My team and Everyone pages, as "Edited by commish at (time): added (player) at (spot)". Reopening a team is listed the same way, and so is each spot changed when a reopened team is submitted after the lock. The Commish page also deletes a person and everything they entered; the commish cannot delete their own team.
- **Lock time:** `pickem.py lock 2026-11-26T18:11Z` locks and shows every team at that UTC time instead of first kickoff; restart `serve` to apply it.
- **Late flex:** a locked team that was saved without a FLEX can add one once, from a game that has not kicked off.
- **Tiebreaker:** on the My team page each person picks the winner of the day's last game and its total score, changeable until that game kicks off and hidden from others until then. Once that game is final, equal fantasy totals are ordered by the right winner first, then the closest total.
- **Game pick'em:** a separate contest on the My team page. Each person may pick the winner of each game and over or under on its total points; the most right picks wins, apart from the fantasy standings. `pickem.py lines` loads each game's over/under line from ESPN and keeps a line already set; a final total equal to the line counts for neither side. Picks lock and show with the teams, or at the time set by `pickem.py lock-picks 2026-11-26T18:45Z`.
- **Reveal:** nobody sees another person's team until the day's first kickoff. After that the Everyone page is a leaderboard that refreshes about once a minute. It lists only people who picked a roster and says how many people without a team are left off; a team with a spot the commish emptied still shows. On it, another person's player shows only once that player's own game has kicked off, and a commish note naming such a player is held back the same way, because a late flex or a commish change can still pick from a game that has not started. Each person always sees their own full team, and the commish's "Edit team" page shows every spot.
- **Score updates:** the My team and Everyone pages say when ESPN last answered ("Scores updated (time)"). For five minutes after a player's points change, the gain or loss shows in green or red beside the points. The first scores after `serve` starts mark no changes.
- **Player stats:** once a player's game has kicked off, the My team and Everyone pages list under the player's name each stat that scored and its points, such as "80 rush yds +8 · 1 rush TD +6"; the entries add up to the player's points. A kicker shows field goals and extra points as made/attempted, and a defense always ends with its points allowed. `STAT_LABELS` and `DEFENSE_LABELS` in espn.py hold the wording.
- **Projected scores and minutes left:** while a player's game still has time on the clock, "proj" under the player's points is the points so far plus the part of ESPN's pregame projection that matches the game time left, so it starts at the projection and ends at the real points. Each team shows the sum as "Projected", with how many of its players still have game time and their minutes left added together (60 per player before kickoff, 0 once final; overtime counts what its clock shows). A team's projection counts players other people cannot see yet, so a team with one hidden player gives away that player's projection.
- **Compact tab:** the Everyone page has a Teams tab (every roster) and a Compact tab (`/teams?view=compact`): one row per team with points, projected score and minutes left.
- **Team name and picture:** the My team page has a "Add a team name and picture" link. Both show on the Everyone page beside the person's name and can be changed at any time, also after the lock. The browser crops a photo to a square and shrinks it before sending; the server keeps PNG, JPEG, GIF or WebP up to 512 KB in pickem.db and refuses anything else. As with teams, anyone who types a person's name can change that person's name and picture.
- **Scoring:** full-point PPR from ESPN's box score; the tables are `PLAYER_POINTS`, `DEFENSE_POINTS` and `POINTS_ALLOWED_TIERS` in espn.py. Two-point conversions, safeties, blocked kicks and field-goal distance bonuses are not scored.
- **Ranking:** each position's list is ordered best first by ESPN's projected points for the current week, shown after each name. `init` loads them; `pickem.py projections` refreshes them, then restart `serve`. The numbers use ESPN's standard full-PPR scoring (`FANTASY_SCORING` in espn.py), not a private league's own scoring.
- **Version:** every page ends with "Version 1.(commits) (commit hash)" and the time the server started. `serve` reads it from git at startup, so each commit changes it; "+changes" after the hash means the running files differ from that commit. Commit, then restart `serve`, to deploy a new version.
- **Refused saves:** a save from an out-of-date page, or a commish action from a browser logged in as someone else, shows a page that says so. `serve` prints one line per save and per refused request.
- **Hall of fame:** the Hall of fame page lists each year's winner, newest first, with that year's scores when they are on file. Past years live in hall_of_fame.json, which is kept in git because pickem.db is deleted for each new contest. Once every game is final the page shows this year's standings (the same people and order as the leaderboard) and the top of the game pick'em, and the commish gets a "Save (year) to the hall of fame" button that writes the year into the file, replacing an earlier save of the same year. Commit the file after saving. The 2021 scores come from teams.ini and scores.ini.
- **Other days:** `pickem.py init --date YYYYMMDD` loads a different game day. Save the finished year to the hall of fame, then delete pickem.db to start a new contest.

## Notes
The models are in models.py which is mostly the string output methods.
The startup.py is the core code. If you need a major logic change it will be there.

After running if any names or scores show up with yellow, you may need to ensure the player is added to the scores.ini
If there are any red scores, make sure you made them more than 0