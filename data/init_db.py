import sqlite3

connection = sqlite3.connect('data/database.db')


with open('data/schema.sql', encoding='UTF-8') as f:
    connection.executescript(f.read())

cur = connection.cursor()

cur.execute("INSERT INTO seasons (year) VALUES (?)",([2020]))
cur.execute("INSERT INTO seasons (year) VALUES (?)",([2021]))
year = cur.lastrowid


cur.execute("INSERT INTO teams (name, season_id) VALUES (?, ?)",("Shane", year,))
shane = cur.lastrowid
cur.execute("INSERT INTO teams (name, season_id) VALUES (?, ?)",("Preston", year,))
preston =cur.lastrowid
cur.execute("INSERT INTO teams (name, season_id) VALUES (?, ?)",("Tommy", year,))
tommy = cur.lastrowid

cur.execute("INSERT INTO players (name, position, score, season_id) VALUES (?,?,?,?)", ("Allen", "qb", 26.7, year,))
allen = cur.lastrowid
cur.execute("INSERT INTO players (name, position, score, season_id) VALUES (?,?,?,?)", ("Pollard", "rb", 16.8, year,))
pollard = cur.lastrowid
cur.execute("INSERT INTO players (name, position, score, season_id) VALUES (?,?,?,?)", ("Diggs", "wr", 20.4, year,))
diggs = cur.lastrowid

cur.execute("INSERT INTO teams_players (player_id, team_id) VALUES (?,?)", (allen, shane,))
cur.execute("INSERT INTO teams_players (player_id, team_id) VALUES (?,?)", (pollard, shane,))
cur.execute("INSERT INTO teams_players (player_id, team_id) VALUES (?,?)", (diggs, shane,))


cur.execute("INSERT INTO teams_players (player_id, team_id) VALUES (?,?)", (allen, preston,))
cur.execute("INSERT INTO teams_players (player_id, team_id) VALUES (?,?)", (diggs, preston,))


cur.execute("INSERT INTO teams_players (player_id, team_id) VALUES (?,?)", (diggs, tommy,))

connection.commit()
connection.close()
