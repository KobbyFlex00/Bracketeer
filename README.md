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
| Ratings | Elo carried across tournaments (K configurable) | Elo carried across tournaments (K configurable) | — (ranked by points across tournaments) |

For every sport:
- **Live public site**: standings, pairings/fixtures, crosstable or bracket, and player/team profiles. Live tournaments auto-refresh, and there is a search box.
- **Career ratings & rankings**: each player has one career profile per sport. Their rating carries from one
  tournament into the next and moves with every round they play. Each sport's page shows the top players, and
  `/<sport>/rankings` has the full leaderboard (rating, last change, record, win %, titles, best finish). Each
  player's page has a rating-over-time chart and their tournament history.
- **Clubs**: rankings have a tab per club (`/scrabble/rankings?club=ATU`) with that club's leaderboard and top 3
  in each category (rating, biggest climber, wins, win rate, top score, average score, average spread). The
  all-clubs view adds a club table with average rating and results against other clubs. A player keeps one
  rating counting every game, including inter-club ones, and is listed under the club of their latest entry.
- **Verified on Stellar**: a finished tournament can publish a fingerprint (SHA-256) of its results,
  standings and ratings to a Soroban contract on Stellar (`contracts/`). TDs click **Publish to Stellar** on the
  tournament's Overview tab; the public page then shows **✓ Verified on Stellar** (or a warning if the results
  changed afterwards), and `/t/<slug>/verify` checks the live chain and offers `results.json` so anyone can
  recompute the hash themselves. Corrections are published as new versions; old ones stay. Configure with
  `STELLAR_CONTRACT_ID` and `STELLAR_SECRET_KEY`; the same works from the CLI with `flask onchain-publish <slug>`
  (or `--all-finished`) and `flask onchain-verify <slug>`. Run `flask onchain-extend` every few months to keep
  the records live.
- **Admin roles**: the login from `ADMIN_USERNAME` / `ADMIN_PASSWORD` is a **super admin**. On
  **Dashboard → Admins** a super admin adds other admins and ticks the games each one manages (Scrabble,
  Chess, Football, and any game added later). A game admin only sees and changes their own games'
  tournaments, players and imports. Every admin can change their own password under **Account**.
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
- [Neon](https://neon.com) free Postgres stores the data.

1. **Get the database URLs.** The database is Neon project `red-voice-54849345`
   (org `org-lingering-fire-17770382`), branch `production`. With the [Neon CLI](https://neon.com/docs/cli/install)
   signed in (`neon login`, or `NEON_API_KEY` set), run this in the repo root:
   ```bash
   npm i -g neon@latest
   neon link --org-id org-lingering-fire-17770382 --project-id red-voice-54849345 --branch production -y
   neon deploy        # applies neon.ts and writes DATABASE_URL + DATABASE_URL_UNPOOLED to .env.local
   ```
   `neon.ts` declares the provisioned extras (Neon Auth, Object Storage bucket `assets`, an empty
   `functions` slot). The app itself uses only Postgres. `aiGateway` is commented out because the
   Free plan rejects it; uncomment it after upgrading.
   `.env.local` is git-ignored and loaded automatically by the app. You can also copy both URLs from
   Neon Console → **Connect** (toggle *Connection pooling* on for the pooled one).
2. **Deploy the app.** On render.com choose **New → Blueprint** and select this repository. Render reads
   `render.yaml` and asks for three values:
   - `DATABASE_URL`: the **pooled** Neon URL (host contains `-pooler`). The app uses it.
   - `DATABASE_URL_UNPOOLED`: the **direct** Neon URL. Only `flask db upgrade` uses it, because
     migrations need a real session rather than the pooler.
   - `ADMIN_PASSWORD`: the TD login password (8+ characters). The username is `admin`; change
     `ADMIN_USERNAME` in Render to pick another.
3. Wait for the deploy to finish, then open `https://<your-app>.onrender.com/admin/` and sign in.
4. **Bring over the old tournaments.** In the dashboard, use **Import** and upload each file from
   `legacy_data/`, or run `flask import-legacy legacy_data/*.json` locally with `.env.local` pointing at Neon.
5. **Tidy up career profiles.** Entries join a profile automatically when the name matches an earlier one.
   On **Dashboard → Players & career profiles**, merge spellings of the same person (e.g. "George" into
   "George Kobby Osae"); the merged spelling is remembered for future tournaments. Give each tournament its
   date in **Settings**, so ratings carry over in the right order (otherwise the order they were created is used).

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
  models.py          Tournament, Player, Participant, Game, AdminUser
  engine.py          round generation (standings + pairing system → saved games)
  ratings.py         Elo, replayed across a sport's tournaments in date order (career ratings)
  onchain.py         result fingerprints and publishing to the Stellar results registry
  players.py         linking tournament entries to career profiles; merge
  rankings.py        cross-tournament leaderboards and player records
  pairing/           swiss.py, round_robin.py, knockout.py, sides.py (pure, unit-tested)
  sports/            scrabble.py, chess.py, football.py — scoring, tie-breaks, result entry
  admin/routes.py    TD dashboard
  public/routes.py   public pages + CSV
  backup.py          JSON backup/restore and legacy import
  templates/ static/
migrations/          database schema (Flask-Migrate / Alembic)
contracts/           Soroban (Stellar) results-registry contract, in Rust
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
