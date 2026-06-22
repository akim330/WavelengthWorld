# Wavelength World

A Flask + SQLite MVP for an online asynchronous Wavelength-style game.

## Features

- Username-only login, case-insensitive accounts
- Independent guesser and cluer panels
- Continuous SVG dial UI
- Player-submitted clues feeding future guesser prompts
- Dynamic global averages
- Dynamic guesser and cluer scores
- Daily and lifetime leaderboards
- Personal history tab with current recalculated scores
- Profanity filtering and duplicate clue prevention
- Seed spectrums and seed clues

## Quickstart

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Then open http://127.0.0.1:5000.

On first run, the app creates `instance/wavelength.sqlite3` and seeds spectra/clues automatically.

## Reset local database

```bash
rm -f instance/wavelength.sqlite3
python app.py
```

## Configuration

Edit `config.py` for scoring bands, leaderboard minimums, and database URL.

## Notes

This is an MVP. Username-only login is intentionally lightweight and not secure for production. For deployment, add real auth, rate limits, admin moderation, and PostgreSQL.
