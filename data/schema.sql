PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS seasons;

CREATE TABLE seasons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    year INTEGER NOT NULL UNIQUE
);


DROP TABLE IF EXISTS players;

CREATE TABLE players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    name TEXT NOT NULL,
    position TEXT NOT NULL,
    score real NOT NULL DEFAULT 0,
    season_id INTEGER NOT NULL,
    UNIQUE (season_id, position, name),
    FOREIGN KEY (season_id)
        REFERENCES seasons (id)
);

DROP TABLE IF EXISTS teams;

CREATE TABLE teams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    name TEXT NOT NULL,
    score real NOT NULL DEFAULT 0,
    season_id INTEGER NOT NULL,
    UNIQUE (season_id, name),
    FOREIGN KEY (season_id)
        REFERENCES seasons (id)
);

DROP TABLE IF EXISTS teams_players;

CREATE TABLE teams_players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    player_id INTEGER NOT NULL,
    team_id INTEGER NOT NULL,
    UNIQUE (player_id, team_id),
    FOREIGN KEY (player_id)
        REFERENCES players (id),
    FOREIGN KEY (team_id)
        REFERENCES teams (id)
);

