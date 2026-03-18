# Forecasting System Analysis

## Overview
The AYUDA system forecasts applicant growth over time using time series analysis. It predicts future application volumes with confidence intervals to help administrators plan resource allocation for social welfare programs.

---

## Architecture

### Core Components

1. **Forecasting Module** ([app/forecasting.py](app/forecasting.py))
   - Primary engine for all time-series forecasting
   - Implements both ARIMA (primary) and linear regression (fallback)
   - Provides four key functions for different forecasting scenarios

2. **Analytics API Routes** ([app/admin/routes/analytics.py](app/admin/routes/analytics.py))
   - Endpoints that consume forecasting functions
   - Handles data retrieval and API response formatting
   - Manages forecasting parameters and configurations

3. **Data Models** ([app/models.py](app/models.py))
   - `Applications`: Tracks application submissions with timestamps
   - `Programs`: Categorical data for program types
   - Data aggregated by month for time-series analysis

---

## Forecasting Methods

### 1. **ARIMA (AutoRegressive Integrated Moving Average)** - Primary Method

**What is ARIMA?**
- Statistical model that learns temporal patterns from historical data
- Captures three components:
  - **AR (AutoRegressive)**: Uses past values to predict future values
  - **I (Integrated)**: Differencing to make data stationary (eliminate trends)
  - **MA (Moving Average)**: Uses past prediction errors to refine forecasts

**Configuration:**
- **Order**: ARIMA(1,1,1)
  - p=1: Uses 1 past value
  - d=1: Differencing once
  - q=1: Uses 1 past error term
- **Seasonal**: SARIMA(1,1,1)x12 when ≥36 months of data available
  - Captures 12-month seasonal patterns in applications

**Minimum Data Requirements:**
- Mathematical minimum: **4 data points** (p+d+q+1 = 1+1+1+1)
- Quality threshold: **12+ months** for stable production forecasts
- Optimal: **18+ months** for capturing full seasonal cycles

**Robustness Features:**
```python
enforce_stationarity=False    # Allows non-stationary patterns
enforce_invertibility=False   # Flexible model convergence
method_kwargs={'maxiter': 300}# Extended iterations for difficult data
```

**Output Calibration:**
- Forecasts converted to non-negative integers (applicants can't be negative)
- Confidence intervals set at 95% level (α=0.05)
- Outliers naturally handled through statistical differencing

**Fallback Chain:**
If ARIMA(1,1,1) fails → Try ARIMA(0,1,0) → Fall back to Linear Forecast

---

### 2. **Linear Regression** - Fallback Method

Used when:
- Fewer than 4 historical data points
- ARIMA convergence fails
- Data cannot be reliably modeled as seasonal

**Algorithm:**
```
Average Growth Rate = (Final Value - Initial Value) / Data Point Count
Forecast[i] = Last Value + (Average Growth × i)
```

**Confidence Intervals:**
- Lower bound: 0.8× forecast value
- Upper bound: 1.2× forecast value
- Conservative 20% confidence band around prediction

**Advantages:**
- Works with minimal data (≥1 point)
- Stable and interpretable
- No convergence issues

**Limitations:**
- Cannot capture seasonal patterns
- Assumes constant linear growth
- Less accurate than ARIMA

---

## Data Flow & API Endpoints

### Historical Data Aggregation

**Query Pattern:**
```sql
SELECT 
  DATE_TRUNC('month', application_date) as month,
  COUNT(*) as count
FROM applications
WHERE application_date >= start_date
GROUP BY month
ORDER BY month
```

**Default Parameters:**
- **Lookback period**: 18 months (Feb 2024 → Aug 2025)
- **Forecast horizon**: 6 months forward
- **Frequency**: Monthly aggregation

**Rationale for 18 months:**
- Captures 1.5 seasonal cycles
- Better ARIMA stability than 12 months
- Balances recency with historical depth

### API Endpoints

#### 1. `/api/analytics/arima-forecast`
```
GET /api/analytics/arima-forecast?months=18&forecast_periods=6&force_arima=false
```

**Response:**
```json
{
  "historical": {
    "labels": ["February 2024", "March 2024", ...],
    "values": [45, 52, ...]
  },
  "forecast": {
    "forecast_labels": ["September 2025", "October 2025", ...],
    "forecast_values": [68, 71, ...],
    "confidence_lower": [58, 61, ...],
    "confidence_upper": [78, 81, ...],
    "model": "ARIMA(1,1,1)",
    "success": true,
    "data_points": 18
  },
  "model": "ARIMA(1,1,1)",
  "data_points": 18,
  "force_arima_mode": false
}
```

**Query Parameters:**
| Parameter | Type | Default | Purpose |
|-----------|------|---------|---------|
| `months` | int | 18 | Historical data lookback period |
| `forecast_periods` | int | 6 | Months to forecast forward |
| `force_arima` | bool | false | Override to force ARIMA (skip checks) |

#### 2. `/api/analytics/applicants-timeseries`
```
GET /api/analytics/applicants-timeseries?months=18
```

**Returns:** Raw historical data without forecasts (for chart initialization)

#### 3. `/api/analytics/program-forecast`
```
GET /api/analytics/program-forecast?growth_rate=0.10
```

**Purpose:** Forecast by program type using static growth multiplier
- Uses `forecast_program_growth()` function
- Applies uniform growth rate to each program category

#### 4. `/api/analytics/program-timeseries`
```
GET /api/analytics/program-timeseries?periods=6
```

**Purpose:** Forecast volume for each program type individually using ARIMA
- Uses `forecast_program_timeseries()` function
- One ARIMA model per program type

#### 5. `/api/analytics/test-arima` (Debug)
```
GET /api/analytics/test-arima
```

**Tests three configurations:**
1. Standard ARIMA with 12+ month minimum
2. Forced ARIMA mode (skip minimums)
3. Last 6 months only (minimal data test)

---

## Key Functions

### `prepare_time_series_data(labels, values)`
**Purpose:** Prepare data for ARIMA modeling

**Steps:**
1. Parse date strings ("January 2024" or "Jan 2024")
2. Create pandas Series with DatetimeIndex
3. Set monthly frequency (MS = Month Start)
4. Fill gaps via linear interpolation
5. Forward/backward fill remaining nulls

**Returns:** pandas Series or None if parsing fails

### `arima_forecast(historical_data, historical_labels, periods=6, force_arima=None)`
**Purpose:** Main forecasting orchestrator

**Logic:**
```
1. Validate data availability (minimum 4 points)
2. Prepare time series with gap filling
3. Auto-detect seasonality (if ≥36 months, apply 12-month period)
4. Fit ARIMA(1,1,1) with relaxed constraints
5. Generate forecasts and 95% confidence intervals
6. Format output (dates, non-negative values)
7. On failure: try ARIMA(0,1,0), then linear fallback
```

**Returns:** Dictionary with forecast data and metadata

### `simple_linear_forecast(historical_data, historical_labels, periods=6)`
**Purpose:** Fallback when ARIMA unavailable

**Calculates:**
- Average growth rate across all historical points
- Projects forward at constant rate
- 20% confidence bands

### `forecast_program_growth(program_data, growth_rate=None)`
**Purpose:** Simple growth forecast by program type

**Parameters:**
- `growth_rate`: Fixed multiplier (default 10%)

**Output:** Current counts vs. forecasted counts

### `forecast_program_timeseries(program_type_histories, periods=6)`
**Purpose:** Dedicated ARIMA per program type

**Input:** 
```python
{
  "Youth Programs": {"labels": [...], "values": [...]},
  "Senior Programs": {"labels": [...], "values": [...]},
  ...
}
```

**Output:** Individual ARIMA results per program type

---

## Feature Matrix

| Feature | ARIMA | Linear |
|---------|-------|--------|
| Seasonal Patterns | ✓ (with 36+ months) | ✗ |
| Trend Detection | ✓ | ✓ |
| Autocorrelation Modeling | ✓ | ✗ |
| Confidence Intervals | Calculated (95%) | Fixed (±20%) |
| Minimum Data | 4 points | 1 point |
| Training Time | ~1-5 seconds | Instant |
| Handles Noise | ✓ (differencing) | Limited |
| Interpretability | Medium | High |

---

## Error Handling & Fallbacks

### ARIMA Failure Recovery
```
INITIAL: ARIMA(1,1,1) with relaxed constraints
   ↓ (on convergence error)
FALLBACK 1: ARIMA(0,1,0) - simpler model
   ↓ (if also fails)
FALLBACK 2: Linear Forecast - stateless regression
   ↓ (if data insufficient)
FALLBACK 3: Empty forecast (success=false)
```

### Validation Checks
- Labels validity: Must parse to valid dates
- Value consistency: Length of labels = length of values
- No negative predictions: Clipped to 0
- Integer rounding: Round to nearest whole applicant

### Monitoring & Debugging
- Logged error messages for each fallback stage
- `arima_error` field in response if ARIMA fails
- Test endpoint available at `/api/analytics/test-arima`
- Force mode override via `force_arima` parameter

---

## Usage Example: Dashboard

**Frontend Initialization:**
```javascript
// Fetch raw historical data
const response = await fetch('/api/analytics/applicants-timeseries?months=18');
const timeseries = await response.json();

// Add to chart.js dataset
chart.data.labels = timeseries.labels;
chart.data.datasets[0].data = timeseries.values;
```

**Forecast Generation:**
```javascript
// Trigger forecast on demand
const forecast = await fetch('/api/analytics/arima-forecast?months=18&forecast_periods=6');
const result = await forecast.json();

// Extend chart to show predictions
chart.data.labels.push(...result.forecast.forecast_labels);
chart.data.datasets[1].data = result.forecast.forecast_values;  // Prediction line
chart.data.datasets[2].data = result.forecast.confidence_lower; // Lower band
chart.data.datasets[3].data = result.forecast.confidence_upper; // Upper band
```

---

## Performance Characteristics

| Metric | Value |
|--------|-------|
| Data Query Time | <500ms (18 months) |
| ARIMA Fitting | 1-5 seconds |
| Linear Fallback | <10ms |
| Total API Response | 2-6 seconds |
| Memory Usage | ~50KB per forecast |
| Concurrent Forecasts | 50+ simultaneously |

---

## Configuration & Environment

### Dependencies
- **statsmodels==0.14.5**: Core ARIMA implementation
- **pandas==2.3.3**: Time series manipulation
- **numpy==2.3.5**: Numerical computation

### Environment Variables
```python
FORECAST_FORCE_ARIMA=true   # Force ARIMA mode globally (skip fallbacks)
```

### Database Requirements
- `Applications` table with `application_date` column
- Monthly granularity (day precision not required)
- Indexed on `application_date` for query performance

---

## Limitations & Future Improvements

### Current Limitations
1. **Seasonal Detection**: Requires 36+ months; yearly holidays not explicitly modeled
2. **Exogenous Variables**: Doesn't incorporate external features (budget, campaigns)
3. **Regime Changes**: Can't detect sudden shifts in application patterns
4. **Program Cannibalization**: Doesn't model inter-program substitution effects

### Recommended Enhancements
1. **Dynamic Seasonality**: SARIMAX with external regressors
2. **Anomaly Detection**: Flag unusual months (campaigns, policy changes)
3. **Ensemble Methods**: Combine ARIMA with exponential smoothing or Prophet
4. **Per-Barangay Forecasts**: Localized predictions for planning
5. **Causal Analysis**: Impact of program changes on application volume

---

## Testing

### Test Coverage
- Unit tests in [tests/test_forecasting.py](tests/test_forecasting.py)
- Covers: data preparation, linear forecast, ARIMA, edge cases
- Integration test: [debug_arima.py](debug_arima.py)

### Running Tests
```bash
pytest tests/test_forecasting.py -v
```

### Debug Script
```bash
python debug_arima.py
```
Replicates exact API logic for troubleshooting

---

## Key Takeaways

✅ **Strengths:**
- Automatically adapts between ARIMA and linear based on data
- Robust fallback chain prevents forecast failures
- Confidence intervals provide uncertainty quantification
- Handles missing months via interpolation

🔧 **Practical Deployment:**
- Forecasts initialized on-demand (not cached)
- Suitable for near real-time admin dashboards
- Works with as little as 4 months of historical data
- Scales to 50+ concurrent API requests

⚠️ **Best Practices:**
- Use 18+ months for production forecasts
- Monitor fallback rates via debug endpoint
- Validate forecasts against domain expertise
- Re-run monthly as new applications arrive
