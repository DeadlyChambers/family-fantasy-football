import utils
import warnings
from dataclasses import dataclass
from datetime import datetime, timedelta
from yachalk import chalk

@dataclass
class Player:
    def __init__(self, positions: list, name: str, score: float, valid: bool = True):
        self.positions = positions
        self.name = name
        self.score = score
        self.valid = valid
        return
    def __str__(self):
        score_color = chalk.bold.white
        name_color = chalk.bold.cyan
        if float(self.score) == 0:
            name_color = chalk.bold.red
            score_color = chalk.bold.red
        if self.valid == False:
            name_color = chalk.bold.yellow
            score_color = chalk.bold.yellow
        temp = name_color(f'{self.name.capitalize(): <{22}}') +  score_color(f'{str(self.score): <{6}}')
        pos = ",".join(self.positions)
        return  temp + " at " + pos

@dataclass
class Team:
    def __init__(self, name:str):
        self.players = []
        self.name = name
        self.score = 0
        return
    
    def add_player(self, player: Player):
        """Adds a player to the team

        Args:
            player (Player): The player with scores included
        """
        self.players.append(player)
        self.score += float(player.score)

    def tostring(self, score:float = 0, verbose:bool = False):
        """Simple method to output the team in different ways for output

        Args:
            score (float, optional): The score that is considered the winning score. Defaults to 0.
            verbose (bool, optional): Setting to true will output all players and scores on team. Defaults to False.

        Returns:
            list: The team as a readable string, much like ToString in c#
        """
        temp: str = ""
        text_color = chalk.bold.gray
        score_bg = chalk.bg_white
        if (score > 0 and score == self.score):
            text_color = chalk.bold.green
            score_bg = chalk.bg_black

        space = "------------------------------------------\n"
        name_text = space+f'{self.name.capitalize(): <{12}}'
        if verbose:
            score_bg = chalk.bg_black
            for _player in self.players:
                temp += "-- "+str(_player)+"\n"
                name_text = self.name.capitalize()+ "\n" +space
        if any(player.valid == False for player in self.players):
            score_bg = chalk.bold.yellow

        return text_color(name_text + temp +f'{"": <{25}}' +  score_bg(f'{str(round(self.score,2)): <{6}}') + "\n"  + space)
        
