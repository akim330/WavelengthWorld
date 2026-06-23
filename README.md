# Wavelength World

A Flask + SQLite MVP for an online asynchronous Wavelength-style game.

## Features

- Lightweight password login with first-return password setup for older accounts
- Optional recovery email storage and private guest play
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

This is an MVP. Login is intentionally lightweight: recovery emails are stored for future/manual help, but automatic password reset emails are not implemented yet. For deployment, add rate limits, admin moderation, automated password recovery, and PostgreSQL.
