# 🏆 Bracketeer

A tournament manager for **Scrabble**, **Chess** and **Football**. It started as the
[ATU Scrabble Club](#credits) tournament engine. Each sport has its own section with its own
rules, pairings and tables, and the sports never mix.

Tournament Directors (TDs) run everything from a password-protected web dashboard that works on a phone.
Players and fans follow the live public pages, which refresh themselves during a tournament.

## Features

| | Scrabble | Chess | Football |
|---|---|---|---|
| Formats | Swiss, Round Robin, Double RR, King of the Hill | Swiss, Round Robin, Double RR | League, home & away league, knockout cup, league → knockout play-offs |
| Ranking | Wins → Spread → SOS → Rating | Points → Buchholz → Sonneborn-Berger → Wins → Rating | Points (3/1/0) → Goal difference → Goals scored |
| Extras | Scores *or* winner + spread, bye spread, two-club team battle, club standings | 1–0 / ½–½ / 0–1 entry, colour balancing, bye points setting | Penalty shoot-out winners, seeded bracket with byes |
| Ratings | Elo (K configurable) | Elo (K configurable) | — |

For every sport:
- **Live public site**: standings, pairings/fixtures, crosstable or bracket, and player/team profiles. Live tournaments auto-refresh, and there is a search box.
- **TD dashboard**:
  - Create, rename, archive and delete tournaments.
  - Add players one by one, by pasting a list, or from a CSV.
  - Withdraw a player without losing their results.
  - Pair the next round in one click.
  - Enter or edit results inline.
  - Fix a game: swap sides, change the pairing, clear or delete it. You can also add a forgotten game or undo a whole round.
- **Exports**: standings and results as CSV, full JSON backups with restore, and printable pairings and scorecards.
- **Swiss pairing never repeats a match-up when it can avoid it.** It backtracks instead of falling back to a rematch.
- **No more "ghost points".** Every stat is computed from the games themselves, so nothing is stored twice.

## Free hosting (Render + Neon)

The whole app runs for free with no expiry date:
- [Render](https://render.com) free web service runs the app.
- [Neon](https://neon.tech) free Postgres stores the data.

1. **Create the database.** Sign up at neon.tech, create a project, and copy its connection string
   (`postgresql://…?sslmode=require`).
2. **Deploy the app.** On render.com choose **New → Blueprint** and select this repository. Render reads
   `render.yaml` and asks for two values:
   - `DATABASE_URL`: the Neon connection string from step 1.
   - `ADMIN_PASSWORD`: the TD login password (8+ characters). The username is `admin`; change
     `ADMIN_USERNAME` in Render to pick another.
3. Wait for the deploy to finish, then open `https://<your-app>.onrender.com/admin/` and sign in.
4. **Bring over the old tournaments.** In the dashboard, use **Import** and upload each file from
   `legacy_data/`.

Things to know about the free tier:
- The app sleeps after 15 minutes without visitors, and the first visit after that takes about 30 seconds.
  On tournament days you can keep it awake with a free monitor at [cron-job.org](https://cron-job.org)
  pinging `https://<your-app>.onrender.com/healthz` every 10 minutes.
- To change the TD password, update `ADMIN_PASSWORD` in Render and redeploy.

## Run it locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env            # then edit SECRET_KEY and ADMIN_PASSWORD
flask db upgrade                # creates instance/bracketeer.db (SQLite) when DATABASE_URL is empty
flask ensure-admin
flask import-legacy legacy_data/*.json   # optional: load the old tournaments
flask run
```

Then open http://127.0.0.1:5000 (public site) and http://127.0.0.1:5000/admin/ (TD dashboard).

Tests and lint: `pytest` and `ruff check .` (CI runs both on every push).

## Project structure

```
bracketeer/
  __init__.py        app factory
  config.py          settings from environment variables
  models.py          Tournament, Participant, Game, AdminUser
  engine.py          round generation (standings + pairing system → saved games)
  ratings.py         Elo
  pairing/           swiss.py, round_robin.py, knockout.py, sides.py (pure, unit-tested)
  sports/            scrabble.py, chess.py, football.py — scoring, tie-breaks, result entry
  admin/routes.py    TD dashboard
  public/routes.py   public pages + CSV
  backup.py          JSON backup/restore and legacy import
  templates/ static/
migrations/          database schema (Flask-Migrate / Alembic)
tests/               pytest suite
legacy_data/         tournaments from the old atu-scrabble-engine
render.yaml          Render deployment blueprint
```

### Adding a migration after changing models
```bash
flask db migrate -m "describe the change" && flask db upgrade
```

## Credits

Built by **George Kobby Osae (Kobby Flex)**, General Secretary (2025/26), ATU Scrabble Club.
