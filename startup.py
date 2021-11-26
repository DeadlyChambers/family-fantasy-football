import argparse
import myconfigparser
import models
from yachalk import chalk
import pip

def import_or_install(package):
    """Trick method to ensure the colors working on windows for console

    Args:
        package (string): The colorama package
    """
    try:
        c = __import__(package)
        c.init()
    except ImportError:
        pip.main(['install', package])
        import colorama
        colorama.init()
import_or_install('colorama')

def parse_teams(players, teams_config):
    """Creates a persons team using the players with the scores
    after this method runs, the total score for an individual team
    will be calculated

    Args:
        players (list): All players that were gatherd from the scores.ini
        teams_config (list): The teams.ini file before being parsed

    Returns:
        list: The team with players and scores hydrated
    """
    teams = teams_config.sections()
    teams_complete = []
    for team_name in teams:
        _team = models.Team(team_name)
        _players = dict(teams_config[team_name])
        #print("Name: "+team_name)
        for _player_position in _players:
            #print("Position: "+_player_position)
            _value = _players[_player_position]
            _player_names = []
            if isinstance(_value,str):
                _player_names.append(_value)
            else:
                _player_names = _value
            _names = [_name.lower() for _name in _player_names]
            #print("Players: "+",".join(_names))
            _found = []            
            for _player in players:
                if ((_player.name in _names) and (_player_position in _player.positions)):
                    _team.add_player(_player)
                    _found.append(_player.name)
            for _name in _names:
                if _name not in _found:
                    _t = models.Player(positions=[_player_position], name=_name, score=0, valid=False)
                    _team.add_player(_t)
                    print(_t)

        teams_complete.append(_team)
    return teams_complete

def parse_scores(scores_config):
    """Creates the players with the scores from the scores.ini config

    Args:
        scores_config (list): The scores.ini config before being parse
    """
    scores = scores_config.sections()
    players = []
    for position_i in scores:
        _position = []
        _position.append(position_i)
        cur_position = scores_config[position_i]
        if ((position_i == "wr") or (position_i == "te") or (position_i == "rb")):
            _position.append('flex')
        for _name, _score in cur_position.items():
            player = models.Player(positions=_position, name=_name, score=_score)
            players.append(player)
            #player = models.Player(positions=_position, name=cur_position, score=0, valid=False)
        
#            print(player)    
    return players

def parse_args():
    """Parses the args passed in from the python function

    Returns:
        list: returns the arg list as an object
    """
    parser = argparse.ArgumentParser(description="Options for fantasy.py")
    parser.add_argument(
        "--scores-config",
        type=str,
        help="path to scores.ini file which will hold the scores",
        default="scores.ini"
    )
    parser.add_argument(
        "--teams-config",
        type=str,
        help="path to a teams.ini file with your teams",
        default="teams.ini",
    )
    parser.add_argument(
        "-v"
        "--verbose",
        dest='is_verbose',
        help="Display all teams scores",
        action="store_true",
        default=False,
    )
    args = parser.parse_args()
    return args


def main():
    """The core of the entire application
    """
    scores_config = myconfigparser.ConfigParserMultiOpt()
    teams_config = myconfigparser.ConfigParserMultiOpt()
    args = parse_args()

    # read config files
    scores_config.read(args.scores_config)
    teams_config.read(args.teams_config)
    
    # hydrate players with scores
    players = parse_scores(scores_config)
    # hydrate teams with players' scores
    all_teams = parse_teams(players, teams_config)

    best_score = max(team.score for team in all_teams)
    for team in all_teams:
        print(team.tostring(score = best_score, verbose = args.is_verbose))
    
    return

if __name__ == "__main__":
    main()
