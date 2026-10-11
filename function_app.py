"""Azure Functions entry points (Python v2 programming model).

Functions
---------
ceo_daily_report_timer  Weekdays, 10:00 and 11:00 UTC; only the run that lands on
                        6:00 AM America/New_York proceeds (DST-safe).
ceo_daily_report_http   POST /api/reports/ceo-daily?date=YYYY-MM-DD&force=true
                        Manual re-run / backfill. Function-key protected; put
                        Entra ID (App Service Authentication) in front in prod.
health                  GET /api/health - liveness for availability tests.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone

import azure.functions as func

from jarvis.config import load_settings
from jarvis.logging_setup import configure_logging
from jarvis.reports.ceo_daily import run_ceo_report
from jarvis.timeutil import is_report_hour

configure_logging()
log = logging.getLogger("jarvis.functions")
app = func.FunctionApp()


@app.timer_trigger(arg_name="timer", schedule="0 0 10,11 * * 1-5", run_on_startup=False, use_monitor=True)
@app.retry(strategy="exponential_backoff", max_retry_count="4",
           minimum_interval="00:01:00", maximum_interval="00:10:00")
def ceo_daily_report_timer(timer: func.TimerRequest) -> None:
    settings = load_settings()
    now = datetime.now(timezone.utc)
    if not is_report_hour(now, settings.timezone, settings.report_hour_local):
        log.info("Not %s:00 in %s (now %s UTC); skipping this trigger", settings.report_hour_local, settings.timezone, now)
        return
    # Exceptions propagate so the Functions retry policy re-runs the job;
    # idempotency in run_ceo_report prevents a duplicate Teams post.
    result = run_ceo_report(settings)
    log.info("CEO report run %s finished with status %s", result.run_id, result.status)


@app.route(route="reports/ceo-daily", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def ceo_daily_report_http(req: func.HttpRequest) -> func.HttpResponse:
    settings = load_settings()
    try:
        run_date = date.fromisoformat(req.params["date"]) if req.params.get("date") else None
    except ValueError:
        return func.HttpResponse("date must be YYYY-MM-DD", status_code=400)
    force = req.params.get("force", "").lower() == "true"
    try:
        r = run_ceo_report(settings, run_date=run_date, force=force)
    except Exception as exc:
        log.exception("Manual CEO report failed")
        return func.HttpResponse(json.dumps({"status": "failed", "error": type(exc).__name__}),
                                 status_code=500, mimetype="application/json")
    body = {"run_id": r.run_id, "status": r.status, "report_date": r.report_date.isoformat(),
            "skipped": r.skipped, "narrative": r.narrative_source, "errors": r.errors}
    return func.HttpResponse(json.dumps(body), mimetype="application/json")


@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def health(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(json.dumps({"status": "ok"}), mimetype="application/json")
