import argparse
import myconfigparser
import pip
import fantasycore

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
    players = fantasycore.parse_scores(scores_config)
    # hydrate teams with players' scores
    all_teams = fantasycore.parse_teams(players, teams_config)
    best_score = max(team.score for team in all_teams)
    for team in all_teams:
        print(team.tostring(score = best_score, verbose = args.is_verbose))
    return


if __name__ == "__main__":
    main()
