"""FieldRoutes (PestRoutes) -> JARVIS field mapping.

EVERY assumption about the FieldRoutes API lives in this one file.

FieldRoutes does not publish its API reference publicly; it is provided to
customers with API access. The names below follow the long-standing PestRoutes
API conventions (``/{entity}/search`` returns IDs, ``/{entity}/get`` returns
records, ``authenticationKey`` / ``authenticationToken`` credentials), but
anything marked VERIFY must be confirmed against the reference FieldRoutes
gives us and against real responses from
``python scripts/verify_fieldroutes.py --company defenders``, which prints
the actual field names and status values our account returns.
"""

from __future__ import annotations

from datetime import date, datetime

# entity -> (api path segment, id-list key in search response / get request, record list key in get response)
ENDPOINTS: dict[str, tuple[str, str, str]] = {
    "employees": ("employee", "employeeIDs", "employees"),
    "customers": ("customer", "customerIDs", "customers"),
    "subscriptions": ("subscription", "subscriptionIDs", "subscriptions"),
    "appointments": ("appointment", "appointmentIDs", "appointments"),
    "invoices": ("ticket", "ticketIDs", "tickets"),  # FieldRoutes calls invoices "tickets"
    "payments": ("payment", "paymentIDs", "payments"),
}

# Which date filters select the records relevant to a reporting window. An
# entity with several filters is searched once per filter and the IDs merged.
DATE_FILTERS: dict[str, list[str]] = {
    "employees": [],
    "customers": ["dateAdded", "dateCancelled"],
    "subscriptions": ["dateAdded", "dateCancelled"],
    "appointments": ["date"],
    "invoices": ["date"],          # VERIFY: may be "invoiceDate"
    "payments": ["date"],
}

# VERIFY: appointment status codes.
APPOINTMENT_STATUS = {
    "0": "pending",
    "1": "completed",
    "2": "no_show",
    "3": "rescheduled",
    "-1": "cancelled",
    "-2": "cancelled",
}

# VERIFY: employee type codes.
EMPLOYEE_TYPE = {"0": "office", "1": "technician", "2": "sales"}

# VERIFY: payment status codes.
PAYMENT_STATUS = {"1": "successful", "0": "failed", "2": "voided", "-1": "voided"}


def parse_date(value) -> date | None:
    if value in (None, "", "0000-00-00", "0000-00-00 00:00:00"):
        return None
    text = str(value)[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_dt(value) -> datetime | None:
    if value in (None, "", "0000-00-00 00:00:00"):
        return None
    try:
        return datetime.strptime(str(value)[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def money(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _s(value) -> str | None:
    return None if value in (None, "", "0") else str(value)


def map_employee(r: dict) -> dict:
    name = " ".join(x for x in [r.get("fname"), r.get("lname")] if x) or f"Employee {r.get('employeeID')}"
    return {
        "source_id": str(r["employeeID"]),
        "branch_source_id": _s(r.get("officeID")),
        "name": name,
        "role": EMPLOYEE_TYPE.get(str(r.get("type")), "unknown"),
        "active": str(r.get("active", "1")) == "1",
        "source_updated_at": parse_dt(r.get("dateUpdated")),
    }


def map_customer(r: dict) -> dict:
    status = str(r.get("status", "1"))
    return {
        "source_id": str(r["customerID"]),
        "branch_source_id": _s(r.get("officeID")),
        "status": {"1": "active", "0": "inactive", "-3": "frozen"}.get(status, status),  # VERIFY
        "date_added": parse_date(r.get("dateAdded")),
        "date_cancelled": parse_date(r.get("dateCancelled")),
        "lead_source": r.get("source") or None,  # VERIFY: may be sourceID needing lookup
        "source_updated_at": parse_dt(r.get("dateUpdated")),
    }


def map_subscription(r: dict) -> dict:
    cancelled = parse_date(r.get("dateCancelled"))
    return {
        "source_id": str(r["subscriptionID"]),
        "branch_source_id": _s(r.get("officeID")),
        "customer_source_id": _s(r.get("customerID")),
        "service_type": r.get("serviceType") or None,
        "status": "cancelled" if cancelled or str(r.get("active")) == "0" else "active",
        "date_added": parse_date(r.get("dateAdded")),
        "date_cancelled": cancelled,
        "cancellation_reason": r.get("cancellationNotes") or None,  # VERIFY
        "sold_by_source_id": _s(r.get("soldBy")),
        "initial_price": money(r.get("initialServiceTotal")),       # VERIFY
        "recurring_price": money(r.get("recurringCharge")),         # VERIFY
        # Only use a value FieldRoutes itself reports; never estimate it.
        "annual_value": money(r.get("annualRecurringValue")),       # VERIFY
        "source_updated_at": parse_dt(r.get("dateUpdated")),
    }


def map_appointment(r: dict) -> dict:
    return {
        "source_id": str(r["appointmentID"]),
        "branch_source_id": _s(r.get("officeID")),
        "customer_source_id": _s(r.get("customerID")),
        "subscription_source_id": _s(r.get("subscriptionID")),
        "scheduled_date": parse_date(r.get("date")),
        "completed_date": parse_date(r.get("dateCompleted")),
        "status": APPOINTMENT_STATUS.get(str(r.get("status")), "pending"),
        "service_type": r.get("serviceType") or _s(r.get("type")),
        "technician_source_id": _s(r.get("servicedBy")) or _s(r.get("employeeID")),
        "is_initial": str(r.get("isInitial", "0")) == "1",  # VERIFY
        "source_updated_at": parse_dt(r.get("dateUpdated")),
    }


def map_invoice(r: dict) -> dict:
    return {
        "source_id": str(r["ticketID"]),
        "branch_source_id": _s(r.get("officeID")),
        "customer_source_id": _s(r.get("customerID")),
        "appointment_source_id": _s(r.get("appointmentID")),
        "invoice_date": parse_date(r.get("invoiceDate") or r.get("date")),
        "subtotal": money(r.get("subTotal")) or 0.0,
        "tax": money(r.get("taxAmount")) or 0.0,
        "total": money(r.get("total")) or 0.0,
        "balance": money(r.get("balance")),
        "source_updated_at": parse_dt(r.get("dateUpdated")),
    }


def map_payment(r: dict) -> dict:
    return {
        "source_id": str(r["paymentID"]),
        "branch_source_id": _s(r.get("officeID")),
        "customer_source_id": _s(r.get("customerID")),
        "payment_date": parse_date(r.get("date")),
        "amount": money(r.get("amount")) or 0.0,
        "status": PAYMENT_STATUS.get(str(r.get("status")), "successful"),
        "method": str(r.get("paymentMethod")) if r.get("paymentMethod") is not None else None,
        "source_updated_at": parse_dt(r.get("dateUpdated")),
    }


MAPPERS = {
    "employees": map_employee,
    "customers": map_customer,
    "subscriptions": map_subscription,
    "appointments": map_appointment,
    "invoices": map_invoice,
    "payments": map_payment,
}
