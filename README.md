# Wavelength World

A Flask + SQLite MVP for an online asynchronous Wavelength-style game.

## Features

- Lightweight password login with first-return password setup for older accounts
- Optional recovery email with password-reset links and private guest play
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

### Password recovery email

Password resets are delivered through [Resend](https://resend.com). Verify
`wavelengthworld.app` in Resend and authorize
`accounts@wavelengthworld.app` before enabling recovery in production.

Set these environment variables:

```bash
RESEND_API_KEY=re_...
RESEND_FROM_EMAIL="Wavelength World <accounts@wavelengthworld.app>"
SITE_BASE_URL=https://wavelengthworld.app
PASSWORD_RESET_MAX_AGE_SECONDS=1800
```

`RESEND_API_KEY` is required for delivery. The remaining values have the
production defaults shown above. `SECRET_KEY` must also be set to a private,
stable production value because password-reset links are signed with it.

## Notes

This is an MVP. Password recovery is available only for accounts that supplied
a recovery email. Accounts without one, including guests, cannot retrieve a
forgotten password. For deployment, add broader request/IP rate limits, admin
moderation, and PostgreSQL.
