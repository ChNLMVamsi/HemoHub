# HemoHub — Blood Bank Inventory & Transfer Network

Blood components are perishable and expire on different clocks. HemoHub lets a
blood bank track every unit's expiry, flags what's about to spoil, and pushes a
**real-time alert** to the network so another bank can claim the unit before it's
wasted.

## Tech stack
- **Django 4.2** (ASGI) · **Django Channels** for live WebSocket alerts
- **Celery + Beat** for the daily expiry sweep · **Redis** as the Channels layer
  and Celery broker
- **PostgreSQL** in production / SQLite locally · **WhiteNoise** static files
- Tailwind (Play CDN) · deploys on **Render** from a `render.yaml` blueprint

## Run locally

Quick (web + live WebSockets, no Redis needed — uses an in-memory channel layer):
```bash
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo          # demo banks + dated stock
python manage.py runserver
```
Open http://127.0.0.1:8000/ — demo login `redcross` / `hemohub123`.
Log in as `apollo` / `hemohub123` in a second window to watch live alerts.

Full stack with Celery (needs Redis running on :6379), three terminals:
```bash
# set REDIS_URL=redis://localhost:6379/0 in each
python manage.py runserver
celery -A HemoHubProject worker --loglevel=info    # Windows: add --pool=solo
celery -A HemoHubProject beat --loglevel=info
```

## Deploy (Render, free)
1. Push this repo to GitHub.
2. Render → **New → Blueprint** → pick the repo. `render.yaml` creates the web
   service, Postgres, and Redis (Key Value) automatically.
3. After the build, open the app URL, then in the Render **Shell** run
   `python manage.py createsuperuser` and (optionally) `python manage.py seed_demo`.
4. Daily expiry sweep (free): add repo secrets `HEMOHUB_URL` and `CRON_SECRET`
   (matching the web service's generated `CRON_SECRET`); the GitHub Action in
   `.github/workflows/daily-expiry.yml` pings the sweep endpoint each day.

## What it does
- Blood bank registration with per-tenant isolation (each bank sees only its stock)
- Inventory with colour-coded expiry urgency (healthy / ≤7d / ≤3d / expired)
- One-click broadcast of an expiring unit to the transfer network
- Cross-bank claim that moves the unit into the claiming bank's inventory
- Live WebSocket toast + badge when a new unit hits the network
- Django admin with CSV bulk import of units
