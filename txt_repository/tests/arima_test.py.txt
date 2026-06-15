import numpy as np
import pandas as pd
from pmdarima.arima import auto_arima
from statsmodels.tsa.statespace.sarimax import SARIMAX
from sklearn.metrics import mean_absolute_error

# 1) Create a clean, regular time series with signal
n = 72                      # 6 years monthly → plenty of seasonal cycles
idx = pd.date_range("2019-01-01", periods=n, freq="MS")  # Month start
t = np.arange(n)
m = 12                      # yearly seasonality for monthly data

y = (
    100
    + 0.7 * t                                  # trend
    + 12 * np.sin(2 * np.pi * t / m)           # seasonality
    + np.random.normal(0, 2, size=n)           # low noise
)
series = pd.Series(y, index=idx).asfreq("MS")  # ensure freq set

# 2) Train/validation split
train, test = series.iloc[:-12], series.iloc[-12:]

# 3) Fit seasonal ARIMA with auto-order search
auto = auto_arima(
    train,
    seasonal=True, m=m,
    d=None, D=None,                # let auto_arima choose differencing
    max_p=3, max_q=3, max_P=2, max_Q=2,
    trace=True,
    error_action="ignore",
    suppress_warnings=True,
    stepwise=True
)

print("Best order:", auto.order, "Best seasonal order:", auto.seasonal_order)

# 4) Refit with SARIMAX for transparency (optional but common in prod)
sarimax = SARIMAX(
    train,
    order=auto.order,
    seasonal_order=auto.seasonal_order,
    enforce_stationarity=False,    # relax constraints for test
    enforce_invertibility=False
).fit(disp=False, maxiter=500)

# 5) Forecast and evaluate vs. a linear baseline
fc_arima = sarimax.get_forecast(steps=len(test)).predicted_mean
# Simple linear baseline (least-squares line on train)
X = np.arange(len(train))
coef = np.polyfit(X, train.values, 1)
fc_lin = coef[0] * np.arange(len(train), len(train) + len(test)) + coef[1]

mae_arima = mean_absolute_error(test, fc_arima)
mae_lin = mean_absolute_error(test, fc_lin)
print(f"MAE ARIMA={mae_arima:.3f}  |  MAE Linear={mae_lin:.3f}")

# 6) Simple gate you can mirror in your app
use_arima = np.isfinite(mae_arima) and (mae_arima <= mae_lin)
print("Select ARIMA?" , use_arima)