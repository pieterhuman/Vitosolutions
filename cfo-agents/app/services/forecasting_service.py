"""Cash flow forecasting primitive used by the forecasting agent.

Inputs:
  - opening bank balance
  - open invoices (expected inflows by due date, with optional lag)
  - open bills (expected outflows by due date)
  - recurring monthly expenses (e.g. payroll, SaaS)
  - VAT reserve fraction

Output: per-day [{date, inflow, outflow, balance}] for `horizon_days`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable

from app.db.models import Bill, Invoice


@dataclass
class ForecastInputs:
    opening_balance: float
    invoices: list[Invoice]
    bills: list[Bill]
    monthly_recurring_outflow: float = 0.0  # payroll + fixed SaaS
    vat_reserve_pct: float = 0.15
    invoice_payment_lag_days: int = 7  # average client payment lateness


@dataclass
class ForecastDay:
    date: date
    inflow: float
    outflow: float
    balance: float


def build_forecast(inputs: ForecastInputs, horizon_days: int) -> list[ForecastDay]:
    today = date.today()
    days: list[ForecastDay] = []
    balance = inputs.opening_balance

    daily_recurring = inputs.monthly_recurring_outflow / 30.0

    inflows_by_day: dict[date, float] = {}
    for inv in inputs.invoices:
        when = inv.due_date + timedelta(days=inputs.invoice_payment_lag_days)
        net = float(inv.amount_due) * (1 - inputs.vat_reserve_pct)
        inflows_by_day[when] = inflows_by_day.get(when, 0.0) + net

    outflows_by_day: dict[date, float] = {}
    for b in inputs.bills:
        outflows_by_day[b.due_date] = outflows_by_day.get(b.due_date, 0.0) + float(b.amount_due)

    for i in range(horizon_days):
        d = today + timedelta(days=i)
        inflow = inflows_by_day.get(d, 0.0)
        outflow = outflows_by_day.get(d, 0.0) + daily_recurring
        balance = balance + inflow - outflow
        days.append(ForecastDay(date=d, inflow=inflow, outflow=outflow, balance=balance))
    return days


def runway_days(forecast: Iterable[ForecastDay]) -> int | None:
    """Return the day index at which balance first goes <= 0, or None."""
    for i, day in enumerate(forecast):
        if day.balance <= 0:
            return i
    return None
