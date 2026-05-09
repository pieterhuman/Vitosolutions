# Setup

## Demo mode (no DB, no Xero)

```bash
cp .env.example .env
export CFO_DEMO_MODE=true
pip install -r requirements.txt
uvicorn app.main:app --reload
streamlit run app/ui/dashboard.py
```

Seed data lives in `seed_data/`.

## Full local

```bash
# 1. Postgres
docker run --name cfo-pg -e POSTGRES_USER=cfo -e POSTGRES_PASSWORD=cfo \
  -e POSTGRES_DB=cfo_agents -p 5432:5432 -d pgvector/pgvector:pg16

# 2. Env
cp .env.example .env
# Set CFO_DEMO_MODE=false, fill in CFO_DATABASE_URL, ANTHROPIC_API_KEY, XERO_*

# 3. Migrations
alembic upgrade head
python -m scripts.seed_local   # optional: load seed_data into Postgres

# 4. Run
uvicorn app.main:app --reload
streamlit run app/ui/dashboard.py
```

## Xero OAuth

1. Create an app at https://developer.xero.com/app/manage.
2. Set redirect URI to `http://localhost:8000/api/xero/callback`.
3. Set `XERO_CLIENT_ID` / `XERO_CLIENT_SECRET` in `.env`.
4. Visit `http://localhost:8000/api/xero/connect` and authorize.

## Tests

```bash
pytest
```
