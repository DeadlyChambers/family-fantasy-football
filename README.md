# family-fantasy-football

It is pretty simple. Update the scores.ini with the player scores, and set the teams with player and positions. Then when ready run
```
python -m venv ~/.venv/family-fantasy-football
source ~/.venv/family-fantasy-football/Scripts/activate
python startup.py
deactivate
```

There is another more interesting output if you want to see the individual player scores for a person's team use the verbose flag.
```
python startup.py -v
```
## Web
Running the application with flask you can do
```
export FLASK_APP=web;
export FLASK_ENV=development;
flask run -p 5050;
```

## Db
The database is using Sqlite. Update the schema, and run the init_db.py for the initialization. Add scripts as the table needs to change
```
python data/init_db.py
```

## Notes
The models are in models.py which is mostly the string output methods.
The startup.py is the core code. If you need a major logic change it will be there.

After running if any names or scores show up with yellow, you may need to ensure the player is added to the scores.ini
If there are any red scores, make sure you made them more than 0

[The guide](https://www.digitalocean.com/community/tutorials/how-to-make-a-web-application-using-flask-in-python-3) I used to work on this app was pretty helpful in regards to flask and sqlite