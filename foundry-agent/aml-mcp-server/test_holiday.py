"""End-to-end test: holiday validation + local model prediction.

Tests both explicit holiday_name and auto-lookup (holiday_name=None).
"""
import holidays
import pandas as pd
import mlflow.sklearn
from datetime import date
from pathlib import Path

# Country name -> ISO code mapping (same as main.py)
_CODES = {"united states": "US", "japan": "JP", "canada": "CA", "germany": "DE"}

MODEL_PATH = str(Path(__file__).resolve().parents[2] / "outputs" / "model")

print(f"Loading model from {MODEL_PATH} ...")
model = mlflow.sklearn.load_model(MODEL_PATH)
print(f"Model loaded: {type(model).__name__}\n")

# (country, date, holiday_name or None for auto-lookup)
tests = [
    ("United States", "2026-07-04", "Independence Day"),   # explicit name
    ("United States", "2026-07-04", None),                  # auto-lookup
    ("United States", "2026-05-07", None),                  # not a holiday
    ("United States", "2026-12-25", None),                  # auto-lookup
    ("United States", "2026-03-15", None),                  # not a holiday
    ("United States", "2026-01-01", None),                  # auto-lookup
    ("Japan",         "2026-01-01", None),                  # auto-lookup (JP)
    ("United States", "2026-06-10", None),                  # not a holiday
    ("United States", "2026-11-26", None),                  # auto-lookup
    ("Canada",        "2026-07-01", None),                  # auto-lookup (CA)
]

print(f"{'Country':15s} {'Date':12s} {'Resolved Name':25s} {'Step 1':10s} {'Step 2 (Model)':15s}")
print("-" * 90)

for country, d, name in tests:
    dt = date.fromisoformat(d)

    # Step 1: holiday validation + auto-lookup
    code = _CODES.get(country.lower())
    country_hols = holidays.country_holidays(code, years=dt.year) if code else {}
    is_holiday = dt in country_hols

    if not is_holiday:
        display_name = name or "(n/a)"
        print(f"{country:15s} {d:12s} {display_name:25s} {'BLOCKED':10s} {'--':15s}")
        continue

    # Auto-resolve name from library if not provided
    resolved_name = name if name else country_hols.get(dt)

    # Step 2: call the model locally (same features as main.py sends)
    row = pd.DataFrame([{
        "countryOrRegion": country,
        "holidayName": resolved_name,
        "normalizeHolidayName": resolved_name,
        "date_year": dt.year,
        "date_month": dt.month,
        "date_day": dt.day,
        "date_dayofweek": dt.weekday(),
    }])
    prediction = model.predict(row)[0]
    paid = "PAID" if str(prediction) == "True" else "NOT PAID"
    src = "(auto)" if name is None else "(explicit)"
    print(f"{country:15s} {d:12s} {resolved_name + ' ' + src:25s} {'HOLIDAY':10s} {paid:15s}")
