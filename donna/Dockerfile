# Local demo image only. Production runs on Azure Functions
# (function_app.py) — see OPERATOR.md. This image is for
# `docker compose up` so the MVP can be clicked through and shown to
# the client against synthetic data, nothing more.
FROM python:3.11-slim

WORKDIR /app

COPY requirements-demo.txt ./
RUN pip install --no-cache-dir -r requirements-demo.txt

COPY src/ ./src/
COPY tests/ ./tests/
COPY demo/ ./demo/

EXPOSE 8080

CMD ["python", "-m", "demo.server"]
