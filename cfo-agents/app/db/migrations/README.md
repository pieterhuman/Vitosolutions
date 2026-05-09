# Migrations

Alembic is configured to autogenerate from `app.db.models`. For the MVP demo
mode we bypass Alembic and use `Base.metadata.create_all()` against an
in-memory SQLite database (see `app/db/models.py::create_all`).

To enable real migrations:

```bash
alembic init -t async app/db/migrations
# Edit alembic.ini to point sqlalchemy.url at CFO_DATABASE_URL
# Edit env.py to import: from app.db.models import Base
# target_metadata = Base.metadata
alembic revision --autogenerate -m "init"
alembic upgrade head
```
