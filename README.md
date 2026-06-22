# Friday River Brief

Fetches live Canterbury river flow data every Friday morning, generates a
weekend paddling brief using Claude AI, and emails it to you.

## Setup (15 minutes)

### 1. Create a private GitHub repo

Go to github.com, create a new **private** repo called `river-brief` (or
whatever you like). Don't initialise with a README.

### 2. Push this folder to it

```bash
cd river-brief-scheduler
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_USERNAME/river-brief.git
git push -u origin main
```

### 3. Add secrets to the repo

Go to your repo on GitHub: Settings > Secrets and variables > Actions > New repository secret.

Add these four secrets:

| Secret name | Value |
|---|---|
| `ANTHROPIC_API_KEY` | Your Anthropic API key from platform.anthropic.com |
| `GMAIL_ADDRESS` | jjbutler74@gmail.com |
| `GMAIL_APP_PASSWORD` | Your Gmail App Password (16 chars, no spaces) |
| `TO_EMAIL` | jjbutler74@gmail.com (or a different address to send to) |

**Gmail App Password:** Go to myaccount.google.com/security, enable 2-Step
Verification, search "App passwords", create one labelled "River Brief".

### 4. Test it manually

Go to your repo on GitHub: Actions > Friday River Brief > Run workflow.

It will run immediately. Check your inbox within about 60 seconds.

### 5. You're done

It runs automatically every Friday at 7 AM NZT (summer) / 6 AM NZT (winter).
If you want a different time, edit the cron line in `.github/workflows/river_brief.yml`.

## Cron time reference

The cron is set to `0 18 * * 4` (18:00 UTC Thursday):
- NZDT (Oct–Apr, UTC+13): 7:00 AM Friday
- NZST (Apr–Oct, UTC+12): 6:00 AM Friday

To get 7 AM year-round you'd need two cron entries, but 6–7 AM is close enough.

## Customising rivers or thresholds

Edit the `RIVERS` list in `river_brief.py`. Each river has:
- `gauge_url`: ECan or ORC gauge page
- `good_min` / `good_max`: your sweet spot in m³/s
- `low_cutoff` / `high_cutoff`: below/above these it's not worth going
- `notes`: context Claude uses when writing the brief

## Cost

One run uses roughly 2,000–3,000 tokens plus 6 web searches.
At Sonnet 4.6 pricing this is well under $0.10 per week.
