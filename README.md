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

## Notes
The models are in models.py which is mostly the string output methods.
The startup.py is the core code. If you need a major logic change it will be there.

After running if any names or scores show up with yellow, you may need to ensure the player is added to the scores.ini
If there are any red scores, make sure you made them more than 0