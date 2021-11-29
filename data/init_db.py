import sqlite3

connection = sqlite3.connect('data/database.db')


with open('data/schema.sql', encoding='UTF-8') as f:
    connection.executescript(f.read())

cur = connection.cursor()

cur.execute("INSERT INTO seasons (year) VALUES (?)",([2020]))
cur.execute("INSERT INTO seasons (year) VALUES (?)",([2021]))
year = int(cur.lastrowid)


cur.execute("INSERT INTO teams (name, season_id) VALUES (?, ?)",("Shane", year,))
shane = int(cur.lastrowid)
cur.execute("INSERT INTO teams (name, season_id) VALUES (?, ?)",("Preston", year,))
preston =int(cur.lastrowid)
cur.execute("INSERT INTO teams (name, season_id) VALUES (?, ?)",("Tommy", year,))
tommy = int(cur.lastrowid)

cur.execute("INSERT INTO players (name, position) VALUES (?,?)", ("Allen", "qb", ))
allen = int(cur.lastrowid)
cur.execute("INSERT INTO players (name, position) VALUES (?,?)", ("Pollard", "rb",))
pollard = int(cur.lastrowid)
cur.execute("INSERT INTO players (name, position) VALUES (?,?)", ("Diggs", "wr",))
diggs = int(cur.lastrowid)

cur.execute("INSERT INTO teams_players (player_id, team_id, score) VALUES (?,?,?)", (allen, shane,26.7,))
cur.execute("INSERT INTO teams_players (player_id, team_id, score) VALUES (?,?,?)", (pollard, shane,16.8,))
cur.execute("INSERT INTO teams_players (player_id, team_id, score) VALUES (?,?,?)", (diggs, shane,20.4,))


cur.execute("INSERT INTO teams_players (player_id, team_id, score) VALUES (?,?,?)", (allen, preston,26.7,))
cur.execute("INSERT INTO teams_players (player_id, team_id, score) VALUES (?,?,?)", (diggs, preston,20.4,))


cur.execute("INSERT INTO teams_players (player_id, team_id, score) VALUES (?,?,?)", (diggs, tommy,20.4,))

connection.commit()
connection.close()
