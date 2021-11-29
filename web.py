from os import name
import sqlite3
from flask import Flask, render_template, request, jsonify
import json

app = Flask(__name__)


# @app.route('/')
# def scores():
#     """Retrieves scores for season in small format

#     Returns:
#         list: Returns the teams with best score
#     """
#     players = get_scores()
#     all_teams = get_teams(players)
#     best_score = max(team.score for team in all_teams)
#     team_string = ""
#     for team in all_teams:
#         team_string += team.tostring(score = best_score)+"\n"
#     return team_string

# @app.route('/verbose')
# def scores_verbose():
#     """Retrieves scores for season in small format

#     Returns:
#         list: Returns the teams with best score and verbose
#     """
#     players = get_scores()
#     all_teams = get_teams(players)
#     best_score = max(team.score for team in all_teams)
#     team_string = ""
#     for team in all_teams:
#         team_string += team.tostring(score = best_score, verbose=True)+"\n"
#     return team_string

####################################
#       Seasons
####################################
@app.route('/')
@app.route('/seasons')
def get_seasons():
    """Simple page return

    Returns:
        page: Returns index.html using render template
    """
    conn = get_db_connection()
    seasons = conn.execute('SELECT * FROM seasons').fetchall()
    conn.close()
    return render_template('index.html', seasons=seasons)

@app.route('/seasons/<int:year>')
def get_season(year):
    """Get Season by year

    Returns:
        page: Returns index.html using render template
    """
    conn = get_db_connection()
    
    season = conn.execute('SELECT * FROM seasons where year = ?',(int(year),)).fetchone()
    teams = conn.execute('SELECT t.name, t.created, t.score, s.year FROM teams t join seasons s on s.id = t.season_id where s.year = ?',(year,)).fetchall()
    conn.close()
    seasons = []
    if season is None:
        print('crap')
    else:
        seasons.append(season)
    return render_template('index.html', seasons=seasons, teams=teams, show_teams=True)

@app.route('/seasons/<int:year>/teams')
def get_teams(year):
    """Get Teams by season

    Returns:
        page: Returns index.html using render template
    """
    conn = get_db_connection()
    teams = conn.execute('SELECT t.name, t.created, t.score, s.year FROM teams t join seasons s on s.id = t.season_id where s.year = ?',(year,)).fetchall()
    conn.close()
    return render_template('teams.html', teams=teams, year=year)

@app.route('/seasons/create', methods=['POST'])
def create_season():
    """Create a new season

    Returns:
        [type]: [description]
    """
    year_str = request.form.get('year')
    if year_str is None or year_str.isnumeric() == False:
        # index.html
        return get_seasons()
    year = int(year_str)
    conn = get_db_connection()
    conn.execute('INSERT INTO seasons (year) VALUES (?)',(year,))
    conn.close()
    # teams.html
    return get_teams(year)

####################################
#       Teams
####################################
@app.route('/teams/create', methods=['POST'])
def create_team():
    """Create team navigation

    Returns:
        [type]: [description]
    """
    name = request.form.get('name')
    year_str = request.form.get('year')
    if year_str is None or year_str.isnumeric() == False:
        # index.html
        return get_seasons()
    year = int(year_str)
    if name is None or name == "":
        # teams.html
        return get_teams(year)
    conn = get_db_connection()
    seasonid = int(conn.execute('SELECT id FROM seasons where year = ?',((int(year),))).fetchone()[0])
    conn.execute('INSERT INTO teams (name, season_id) VALUES (?,?)',(name,seasonid,))
    conn.close()
    # teams.html
    return get_teams(year)

@app.route('/teams/<name>')
def get_team(name):
    """Get Team by name, and param by year

    Returns:
        page: Returns index.html using render template
    """
    return get_season_team(name, request.args.get('year'))
    
def get_season_team(name, year):
    """Return the Team by Season which is where you would add a player

    Args:
        name ([type]): [description]
        year ([type]): [description]

    Returns:
        [type]: [description]
    """
    conn = get_db_connection()
    teams = []
    players = []
    update_team_score(teamname=name)
    if year is None or year.isnumeric() == False:
        teams = conn.execute('SELECT t.name, t.created, t.score, s.year, t.id '
                            'FROM teams t join seasons s on s.id = t.season_id where t.name = ?',(name,)).fetchall()
    else:
        team = conn.execute('SELECT t.name, t.created, t.score, s.year, t.id '
                            'FROM teams t '
                            'join seasons s on s.id = t.season_id '
                            'where s.year = ? and t.name = ?',(int(year),name,)).fetchone()
        teams.append(team)
        players = conn.execute('SELECT p.name, p.position, tp.score, p.id, tp.id as team_player_id '
                            'FROM teams_players tp '
                            'join players p on p.id = tp.player_id '
                            'where tp.team_id = ?',(int(team['id']),)).fetchall()
    conn.close()
    if teams is None:
        return get_teams(int(year))
    return render_template('teams.html', teams=teams, players=players, year=int(year), name=name)

@app.route('/teams/<name>/players', methods=['POST'])
def player_add(name):
    """Add a player to a team, the player should already be created at this point

    Args:
        name (string): The name of the team

    Returns:
        [type]: To the Team page
    """
    playerid = request.form.get('player_id')
    yearid = request.form.get('year')
    if yearid is None or yearid.isnumeric() == False:
        return get_teams()
    year = int(yearid)        
    if playerid is None or playerid.isnumeric() == False:
        return get_teams(year)
    player_id = int(playerid)
    conn = get_db_connection()
    season_id = int(conn.execute('SELECT id FROM seasons year = ? and ',(year,)).fetchone()[0])
    team_id = int(conn.execute('SELECT id FROM teams name = ? and season_id = ?',(name,season_id,)).fetchone()[0])
    conn.execute("INSERT INTO teams_players (player_id, team_id) VALUES (?,?)", (player_id, team_id,))
    conn.close()
    update_team_score(seasonid=season_id)
    return get_season_team(name, year)

####################################
#       Players
####################################
@app.route('/players/create', methods=['POST'])
def create_player():
    """Create a player BEFORE adding a player

    Returns:
        [type]: Create a player
    """
    teamid = request.form.get('team_id')
    position = request.form.get('position')
    name = request.form.get('name')
    score = request.form.get('score')
    if teamid.isnumeric() == False:
        return get_seasons()
    team_id = int(teamid)
    conn = get_db_connection()
    team = conn.execute('SELECT season_id, name FROM teams id = ?',(team_id,)).fetchone()
    if position is None or position == "" or name is None or name == "":
        return get_team(team[1])
    if score is None or score.isnumeric() == False:
        score = 0
    else:
        score = int(score)
    conn.execute('INSERT into players (name, position) VALUES (?,?)', (name, position,))
    player_id = int(conn.lastrowid)
    conn.execute("INSERT INTO teams_players (player_id, team_id, score) VALUES (?,?,?)", (player_id, team_id,score))
    update_team_score(teamid=team_id)
    conn.close()
    return get_team(team[1])

@app.route('/teamplayers/<int:teamplayerid>', methods=['PUT'])
def update_team_player_score(teamplayerid):
    """Update score

    Args:
        teamplayerid ([type]): [description]

    Returns:
        [type]: [description]
    """
    conn = get_db_connection()
    new_score = request.form.get('new_score')
    if new_score is None or new_score.isnumeric() == False:
        return jsonify(message="Score was not present in request", success="false")
    teamplayer = conn.execute('SELECT tp.score, tp.team_id, t.season_id FROM teams_players tp join teams t on tp.team_id = t.id WHERE tp.id = ? ',(int(teamplayerid),)).fetchone()
    old_score = int(teamplayer[0])
    new_score = int(new_score)
    if old_score == new_score:
        return jsonify(message="Score provided matched score in db", success="false")
    delta_score = new_score - old_score
    #TODO update TP.score, and subtract delta score commit
    
    
    conn.commit()
    conn.close()
    update_team_score(teamid=int(teamid))
    


@app.route('/teams/<int:teamid>/players/<int:playerid>', methods=['DELETE'])
def delete_team_player(teamid, playerid):
    """Delete player id

    Args:
        teamid ([type]): [description]
        id ([type]): [description]

    Returns:
        [type]: [description]
    """
    conn = get_db_connection()
    conn.execute('DELETE FROM teams_players WHERE player_id = ? and team_id = ?',(int(playerid), int(teamid),))
    conn.commit()
    conn.close()
    update_team_score(teamid=int(teamid))
    conn = get_db_connection()
    score = int(conn.execute('SELECT score FROM teams_players WHERE player_id = ? and team_id = ?',(int(playerid), int(teamid),)).fetchone()[0])
    conn.commit()
    conn.close()
    return jsonify(score=score)

def update_team_score(teamid = None, seasonid = None, teamname = None):
    """Update a teams score by season, or by team

    Args:
        seasonid ([type]): [description]
        teamid ([type]): [description]

    Returns:
        [type]: [description]
    """
    conn = get_db_connection()
    teamids = []
    if teamid is not None:
        teamids.append(int(teamid))
    elif seasonid is not None:
        teams = conn.execute("SELECT id FROM teams WHERE season_id = ?",(int(seasonid),)).fetchall()
        for team in teams:
            teamids.append(int(team[0]))
    elif teamname is not None:
        teams = conn.execute("SELECT id FROM teams WHERE name = ?",(name,)).fetchall()
        for team in teams:
            teamids.append(int(team[0]))
    for team_id in teamids:
        conn.execute('UPDATE teams SET score = round((SELECT SUM(score) FROM teams_players WHERE team_id = :teamid),2) WHERE id = :teamid',{"teamid":team_id})
        conn.commit()
    conn.close()


@app.route('/players/<int:id>', methods=['GET', 'DELETE'])
def get_player(id):
    """Get Teams by season

    Returns:
        page: Returns index.html using render template
    """
    conn = get_db_connection()
    if request.method == 'DELETE':
        conn.execute('UPDATE players SET active = 0 WHERE player_id = ?',(int(id),))
        conn.commit()
        conn.close()
        return jsonify(data="true")
    players = []
    player = conn.execute('SELECT * FROM players id = ?',(id,)).fetchone()
    players.append(player)
    conn.close()
    return render_template('players.html', player=player)

@app.route('/players', methods=['GET'])
def get_players():
    """Used to get players by name, or all

    Returns:
        [type]: [description]
    """
    search = request.args.get('qry')
    is_active = 1
    if request.args.get('active') == 'false':
        is_active = 0
    sql = 'SELECT id as value, (name || " " || position) as text FROM players WHERE active = :is_active order by name desc, position asc LIMIT 20'
    if name is not None:
        sql = 'SELECT id as value, (name || " " || position) as text FROM players where active = :is_active and (name like :search or position like :search) order by name desc, position asc LIMIT 20'
    conn = get_db_connection()
    players = conn.execute(sql,{'search': '%'+search+'%', 'is_active': is_active}).fetchall()
    conn.close()
    return jsonify([dict(ix) for ix in players])

@app.route('/icons')
def icons_page():
    return render_template('icons.html')

# def get_config_scores(path:str = 'scores.ini'):
#     """Removing the need for printing straight to console
#     """
#     scores_config = myconfigparser.ConfigParserMultiOpt()
#     # read config files
#     scores_config.read(path)
#     # hydrate players with scores
#     players = fantasycore.parse_scores(scores_config)
#     return players

# def get_config_teams(players, path:str = 'teams.ini'):
#     """Return teams with the use of the config

#     Args:
#         players (list): The players gathered from the get_players method
#     """
#     teams_config = myconfigparser.ConfigParserMultiOpt()
#     # read config files
#     teams_config.read(path)
#     # hydrate teams with players' scores
#     all_teams = fantasycore.parse_teams(players, teams_config)
#     return all_teams

def get_db_connection():
    conn = sqlite3.connect('data/database.db')
    conn.row_factory = sqlite3.Row
    return conn