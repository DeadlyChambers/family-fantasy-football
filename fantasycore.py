import models

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
        for _player_position in _players:
            _value = _players[_player_position]
            _player_names = []
            if isinstance(_value,str):
                _player_names.append(_value)
            else:
                _player_names = _value
            _names = [_name.lower() for _name in _player_names]
            _found = []
            for _player in players:
                if ((_player.name in _names) and (_player_position in _player.positions)):
                    _team.add_player(_player)
                    _found.append(_player.name)
            for _name in _names:
                if _name not in _found:
                    _missed_player = models.Player(positions=[_player_position], name=_name, score=0, valid=False)
                    _team.add_player(_missed_player)
                    print(_missed_player)

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
    return players
