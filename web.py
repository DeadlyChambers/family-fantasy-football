import sqlite3
from flask import Flask, render_template, request
import myconfigparser
import fantasycore

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

@app.route('/')
@app.route('/seasons')
def get_seasons():
    """Simple page return

    Returns:
        page: Returns index.html using render template
    """
    print("get_seasons")
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
    print("get_season")
    conn = get_db_connection()
    season = conn.execute('SELECT * FROM seasons where year = ?',(year,)).fetchone()
    conn.close()
    seasons = []
    if season is None:
        print('crap')
    else:
        seasons.append(season)
    return render_template('index.html', seasons=seasons)

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

@app.route('/players/<int:id>')
def get_player(id):
    """Get Teams by season

    Returns:
        page: Returns index.html using render template
    """
    conn = get_db_connection()
    players = []
    player = conn.execute('SELECT * FROM players id = ?',(id,)).fetchone()
    
    players.append(player)
    conn.close()
    return render_template('players.html', player=player)

@app.route('/teams/<name>')
def get_team(name):
    """Get Team by name, and param by year

    Returns:
        page: Returns index.html using render template
    """
    year = int(request.args['year'])
    conn = get_db_connection()
    teams = []
    players = []
    if year is None:
        teams = conn.execute('SELECT t.name, t.created, t.score, s.year '
                            'FROM teams t join seasons s on s.id = t.season_id where t.name = ?',(name,)).fetchall()
    else:
        team = conn.execute('SELECT t.name, t.created, t.score, s.year, t.id '
                            'FROM teams t '
                            'join seasons s on s.id = t.season_id '
                            'where s.year = ? and t.name = ?',(year,name,)).fetchone()
        teams.append(team)
        players = conn.execute('SELECT p.name, p.position, p.score, p.id '
                            'FROM teams_players tp '
                            'join players p on p.id = tp.player_id '
                            'where tp.team_id = ?',(team['id'],)).fetchall()
    conn.close()
    if teams is None:
        print('crap')
    return render_template('teams.html', teams=teams, players=players, year=year)


def get_config_scores(path:str = 'scores.ini'):
    """Removing the need for printing straight to console
    """
    scores_config = myconfigparser.ConfigParserMultiOpt()
    # read config files
    scores_config.read(path)
    # hydrate players with scores
    players = fantasycore.parse_scores(scores_config)
    return players

def get_config_teams(players, path:str = 'teams.ini'):
    """Return teams with the use of the config

    Args:
        players (list): The players gathered from the get_players method
    """
    teams_config = myconfigparser.ConfigParserMultiOpt()
    # read config files
    teams_config.read(path)
    # hydrate teams with players' scores
    all_teams = fantasycore.parse_teams(players, teams_config)
    return all_teams

def get_db_connection():
    conn = sqlite3.connect('data/database.db')
    conn.row_factory = sqlite3.Row
    return conn