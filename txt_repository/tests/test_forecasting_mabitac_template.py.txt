"""
Template test for Mabitac MSWDO monthly applicants ARIMA forecasting.
"""

import os

import pandas as pd
import pytest

from app import forecasting


DEFAULT_DATA_PATH = os.path.join(
    os.path.dirname(__file__),
    "data",
    "mabitac_monthly_applicants.csv",
)

MONTH_COLUMN_CANDIDATES = (
    "month",
    "date",
    "period",
    "month_year",
    "monthyear",
)

VALUE_COLUMN_CANDIDATES = (
    "applicants",
    "applicant_count",
    "count",
    "total",
    "received",
    "ayuda_received",
    "beneficiaries",
)


def _resolve_column(df, candidates):
    normalized = {col.lower().strip(): col for col in df.columns}
    for name in candidates:
        if name in normalized:
            return normalized[name]
    return None


def _load_mabitac_monthly_data(path):
    df = pd.read_csv(path)

    month_col = _resolve_column(df, MONTH_COLUMN_CANDIDATES)
    value_col = _resolve_column(df, VALUE_COLUMN_CANDIDATES)

    if not month_col or not value_col:
        raise ValueError(
            "Missing required columns. Expected month/date and applicants/count columns."
        )

    df = df[[month_col, value_col]].rename(
        columns={month_col: "month", value_col: "value"}
    )

    df["month"] = pd.to_datetime(df["month"], errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["month", "value"]).sort_values("month")

    labels = df["month"].dt.strftime("%b %Y").tolist()
    values = df["value"].tolist()
    return labels, values


def test_arima_forecast_with_mabitac_data():
    data_path = os.environ.get("MABITAC_MSWDO_DATA_PATH", DEFAULT_DATA_PATH)
    if not os.path.exists(data_path):
        pytest.skip(
            "Mabitac MSWDO data file not found. "
            "Set MABITAC_MSWDO_DATA_PATH or place the CSV at tests/data/mabitac_monthly_applicants.csv."
        )

    pytest.importorskip("statsmodels")

    labels, values = _load_mabitac_monthly_data(data_path)

    assert len(values) >= forecasting.MIN_FORECAST_DATA_POINTS, (
        "Provide at least 4 monthly data points for ARIMA."
        f" Found {len(values)}."
    )

    result = forecasting.arima_forecast(
        values,
        labels,
        periods=6,
        force_arima=True,
    )

    assert result["forecast_supported"] is True
    assert result["success"] is True
    assert result["model"].startswith("ARIMA")
    assert len(result["forecast_values"]) == 6
    assert len(result["forecast_labels"]) == 6
    assert all(v >= 0 for v in result["forecast_values"])
