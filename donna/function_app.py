"""Azure Functions entry points.

Cron schedules are UTC (tenant runs SAST = UTC+2, no DST):
  poll       every 30 minutes
  digest     04:30 and 14:30 UTC weekdays (06:30 / 16:30 SAST)
  urgent     every 10 minutes
  heartbeat  04:45 and 14:45 UTC weekdays
  POST /api/close/{token}   signed mark-as-done link
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import azure.functions as func
import requests

from donna import config
from donna.engine.poll import run_poll
from donna.http_close import handle_close
from donna.jobs.digest import run_digest
from donna.jobs.heartbeat import run_heartbeat
from donna.jobs.urgent import run_urgent
from donna.telemetry import install

install()

app = func.FunctionApp()


def _now() -> datetime:
    return datetime.now(timezone.utc)


@app.timer_trigger(schedule="0 */30 * * * *", arg_name="timer",
                   run_on_startup=False)
def poll(timer: func.TimerRequest) -> None:
    run_poll(config.graph_client(), config.store(), now=_now())


@app.timer_trigger(schedule="0 30 4,14 * * 1-5", arg_name="timer",
                   run_on_startup=False)
def digest(timer: func.TimerRequest) -> None:
    s = config.store()
    run_digest(config.graph_client(), s, now=_now(),
               token_key=config.close_token_key(),
               dry_run_dir=config.dry_run_dir(s))


@app.timer_trigger(schedule="0 */10 * * * *", arg_name="timer",
                   run_on_startup=False)
def urgent(timer: func.TimerRequest) -> None:
    s = config.store()
    url = s.config_get("teams_webhook_url") or config.teams_webhook_url()

    def post(payload: dict) -> None:
        requests.post(url, json=payload, timeout=30).raise_for_status()

    run_urgent(s, post, now=_now())


@app.timer_trigger(schedule="0 45 4,14 * * 1-5", arg_name="timer",
                   run_on_startup=False)
def heartbeat(timer: func.TimerRequest) -> None:
    run_heartbeat(config.store(), now=_now())


@app.route(route="close/{token}", methods=["POST"],
           auth_level=func.AuthLevel.ANONYMOUS)
def close(req: func.HttpRequest) -> func.HttpResponse:
    status, body = handle_close(
        config.store(), req.route_params.get("token", ""),
        config.close_token_key(), now=_now())
    return func.HttpResponse(json.dumps(body), status_code=status,
                             mimetype="application/json")
