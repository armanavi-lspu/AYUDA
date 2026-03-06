"""
Forecasting module using ARIMA (AutoRegressive Integrated Moving Average) model.
This module provides stable time series forecasting for application trends.
"""

import numpy as np
import pandas as pd
from datetime import datetime
import warnings
import os

# Suppress warnings from statsmodels during model fitting
# FutureWarning suppression removed so pandas/statsmodels deprecations surface early
warnings.filterwarnings('ignore', category=UserWarning)

# Constants for simple linear forecast confidence intervals
CONFIDENCE_LOWER_MULTIPLIER = 0.8
CONFIDENCE_UPPER_MULTIPLIER = 1.2

# Force ARIMA override (set env var FORECAST_FORCE_ARIMA=true or query param)
FORCE_ARIMA_MODE = os.environ.get('FORECAST_FORCE_ARIMA', 'false').lower() == 'true'


def prepare_time_series_data(labels, values):
    """
    Prepare time series data for ARIMA model.
    
    Args:
        labels: List of date labels (strings like 'January 2024')
        values: List of numeric values corresponding to each label
        
    Returns:
        pandas Series with datetime index, properly sorted and gap-filled
    """
    if not labels or not values or len(labels) != len(values):
        return None
    
    # Parse dates from labels
    dates = []
    for label in labels:
        try:
            # Try parsing 'Month Year' format (e.g., 'January 2024')
            date = datetime.strptime(label, '%B %Y')
            dates.append(date)
        except ValueError:
            try:
                # Try parsing 'Mon Year' format (e.g., 'Jan 2024')
                date = datetime.strptime(label, '%b %Y')
                dates.append(date)
            except ValueError:
                # If parsing fails, use index-based dates
                return None
    
    # Create pandas Series with datetime index
    series = pd.Series(values, index=pd.DatetimeIndex(dates))
    
    # Sort by index and set monthly frequency
    series = series.sort_index()
    series = series.asfreq('MS')  # Month Start frequency
    
    # Fill gaps with interpolation
    if series.isnull().any():
        series = series.interpolate(method='linear', limit_direction='both')
        # Modern pandas 2.0+ API: use ffill() and bfill() directly
        # (fillna(method=...) was removed in pandas 2.2+)
        series = series.ffill().bfill()
    
    return series


def arima_forecast(historical_data, historical_labels, periods=6, force_arima=None):
    """
    Generate forecasts using ARIMA model with improved robustness.
    
    Args:
        historical_data: List of historical values
        historical_labels: List of date labels for historical data
        periods: Number of future periods to forecast (default: 6)
        force_arima: Override to force ARIMA mode (default: None, uses env var)
        
    Returns:
        dict with forecast_labels, forecast_values, confidence_lower, confidence_upper
    """
    # Check force mode
    force_mode = force_arima if force_arima is not None else FORCE_ARIMA_MODE
    
    try:
        from statsmodels.tsa.arima.model import ARIMA
        from statsmodels.tools.sm_exceptions import ConvergenceWarning
        warnings.filterwarnings('ignore', category=ConvergenceWarning)
    except ImportError:
        # Fallback to simple linear forecast if statsmodels is not available
        return simple_linear_forecast(historical_data, historical_labels, periods)
    
    # ARIMA(1,1,1) requires at minimum p+d+q+1 = 4 observations.
    # The previous 12-point threshold was a quality preference, not a mathematical
    # requirement, and caused unconditional fallbacks for the first year of deployment.
    # ARIMA(1,1,1) mathematically requires p+d+q+1 = 4 observations. The previous
    # 12-point threshold was a quality preference that caused fallbacks during early
    # deployment. Four points enable forecasting during initial data collection; 12+
    # points remain recommended for stable forecasts.
    MIN_ARIMA_POINTS = 4
    if not historical_data or len(historical_data) < MIN_ARIMA_POINTS:
        return simple_linear_forecast(historical_data, historical_labels, periods)
    
    # Prepare time series with gap filling
    series = prepare_time_series_data(historical_labels, historical_data)
    
    if series is None:
        return simple_linear_forecast(historical_data, historical_labels, periods)
    
    try:
        # Determine seasonality: 12 for monthly data (need ≥36 points for 3 cycles)
        seasonal_order = (0, 0, 0, 0)  # No seasonality by default
        if len(series) >= 36:
            seasonal_order = (1, 1, 1, 12)  # Seasonal ARIMA with 12-month period
        
        # Fit ARIMA model with relaxed constraints for better convergence
        # order=(1, 1, 1): Standard ARIMA configuration
        model = ARIMA(
            series, 
            order=(1, 1, 1),
            seasonal_order=seasonal_order,
            enforce_stationarity=False,  # Relax stationarity constraint
            enforce_invertibility=False  # Relax invertibility constraint
        )
        
        # Fit with default method - use method_kwargs for optimizer options (statsmodels 0.14+)
        fitted_model = model.fit(method_kwargs={'maxiter': 300})
        
        # Generate forecast
        forecast_result = fitted_model.get_forecast(steps=periods)
        forecast_values = forecast_result.predicted_mean.tolist()
        
        # Get confidence intervals
        conf_int = forecast_result.conf_int(alpha=0.05)
        confidence_lower = conf_int.iloc[:, 0].tolist()
        confidence_upper = conf_int.iloc[:, 1].tolist()
        
        # Generate forecast labels
        last_date = series.index[-1]
        forecast_labels = []
        for i in range(1, periods + 1):
            next_date = last_date + pd.DateOffset(months=i)
            forecast_labels.append(next_date.strftime('%b %Y'))
        
        # Ensure non-negative values (applicants can't be negative)
        forecast_values = [max(0, round(v)) for v in forecast_values]
        confidence_lower = [max(0, round(v)) for v in confidence_lower]
        confidence_upper = [max(0, round(v)) for v in confidence_upper]
        
        model_name = f"ARIMA(1,1,1)"
        if seasonal_order != (0, 0, 0, 0):
            model_name += f"x{seasonal_order}12"
        
        return {
            'forecast_labels': forecast_labels,
            'forecast_values': forecast_values,
            'confidence_lower': confidence_lower,
            'confidence_upper': confidence_upper,
            'model': model_name,
            'success': True,
            'data_points': len(series)
        }
        
    except Exception as e:
        # Try fallback configurations
        print(f"⚠️ Initial ARIMA(1,1,1) failed: {str(e)}")
        
        # Fallback 1: Try simpler order (0, 1, 0) - random walk with drift
        try:
            print("  → Trying simpler ARIMA(0,1,0)...")
            model = ARIMA(
                series, 
                order=(0, 1, 0),
                seasonal_order=(0, 0, 0, 0),
                enforce_stationarity=False,
                enforce_invertibility=False
            )
            fitted_model = model.fit(method_kwargs={'maxiter': 200})
                        
            forecast_result = fitted_model.get_forecast(steps=periods)
            forecast_values = forecast_result.predicted_mean.tolist()
            conf_int = forecast_result.conf_int(alpha=0.05)
            confidence_lower = conf_int.iloc[:, 0].tolist()
            confidence_upper = conf_int.iloc[:, 1].tolist()
            
            last_date = series.index[-1]
            forecast_labels = []
            for i in range(1, periods + 1):
                next_date = last_date + pd.DateOffset(months=i)
                forecast_labels.append(next_date.strftime('%b %Y'))
            
            forecast_values = [max(0, round(v)) for v in forecast_values]
            confidence_lower = [max(0, round(v)) for v in confidence_lower]
            confidence_upper = [max(0, round(v)) for v in confidence_upper]
            
            print("  ✓ Fallback ARIMA(0,1,0) succeeded")
            return {
                'forecast_labels': forecast_labels,
                'forecast_values': forecast_values,
                'confidence_lower': confidence_lower,
                'confidence_upper': confidence_upper,
                'model': 'ARIMA(0,1,0) - Fallback',
                'success': True,
                'data_points': len(series)
            }
        except Exception as e2:
            print(f"  ✗ Fallback failed: {str(e2)}")
        
        # Fallback 2: Linear regression if all ARIMA fails
        print("  → Falling back to linear forecast")
        fallback = simple_linear_forecast(historical_data, historical_labels, periods)
        fallback['arima_error'] = str(e)
        return fallback


def simple_linear_forecast(historical_data, historical_labels, periods=6):
    """
    Simple linear trend forecast as fallback when ARIMA is not applicable.
    
    Args:
        historical_data: List of historical values
        historical_labels: List of date labels for historical data
        periods: Number of future periods to forecast
        
    Returns:
        dict with forecast_labels, forecast_values, and empty confidence intervals
    """
    if not historical_data:
        return {
            'forecast_labels': [],
            'forecast_values': [],
            'confidence_lower': [],
            'confidence_upper': [],
            'model': 'none',
            'success': False
        }
    
    # Calculate average growth rate
    if len(historical_data) > 1:
        avg_growth = (historical_data[-1] - historical_data[0]) / len(historical_data)
    else:
        avg_growth = 0
    
    last_value = historical_data[-1] if historical_data else 0
    
    # Generate forecast values
    forecast_values = []
    for i in range(1, periods + 1):
        value = max(0, round(last_value + (avg_growth * i)))
        forecast_values.append(value)
    
    # Generate forecast labels anchored to the last known historical date.
    # Using datetime.now() would create a gap if historical data ends before today.
    forecast_labels = []
    anchor = datetime.now()
    if historical_labels:
        for fmt in ('%B %Y', '%b %Y'):
            try:
                anchor = datetime.strptime(historical_labels[-1], fmt)
                break
            except ValueError:
                continue

    for i in range(1, periods + 1):
        next_date = anchor + pd.DateOffset(months=i)
        forecast_labels.append(next_date.strftime('%b %Y'))
    
    # Simple confidence intervals using defined constants
    confidence_lower = [max(0, round(v * CONFIDENCE_LOWER_MULTIPLIER)) for v in forecast_values]
    confidence_upper = [round(v * CONFIDENCE_UPPER_MULTIPLIER) for v in forecast_values]
    
    return {
        'forecast_labels': forecast_labels,
        'forecast_values': forecast_values,
        'confidence_lower': confidence_lower,
        'confidence_upper': confidence_upper,
        'model': 'linear',
        'success': True
    }


def forecast_program_growth(program_data, growth_rate=None):
    """
    Forecast program category growth.
    
    Args:
        program_data: dict with 'labels' and 'data' for program categories
        growth_rate: Optional custom growth rate (default: calculated from data)
        
    Returns:
        dict with current and forecasted data
    """
    if not program_data or 'data' not in program_data:
        return {
            'labels': [],
            'current_data': [],
            'forecast_data': [],
            'success': False
        }
    
    current_data = program_data.get('data', [])
    labels = program_data.get('labels', [])
    
    if growth_rate is None:
        # Use a conservative 10% growth estimate
        growth_rate = 0.10
    
    # Calculate forecasted values
    forecast_data = [max(0, round(v * (1 + growth_rate))) for v in current_data]
    
    return {
        'labels': labels,
        'current_data': current_data,
        'forecast_data': forecast_data,
        'growth_rate': growth_rate,
        'success': True
    }


def forecast_program_timeseries(program_type_histories, periods=6):
    """
    Forecast per-program-type application volume using ARIMA.

    Unlike forecast_program_growth() which applies a static multiplier,
    this function performs a genuine time-series forecast per program type.

    Args:
        program_type_histories: dict of {program_type: {'labels': [...], 'values': [...]}}
        periods: Number of months to forecast forward

    Returns:
        dict of {program_type: forecast_result_dict}
    """
    results = {}
    for program_type, history in program_type_histories.items():
        labels = history.get('labels', [])
        values = history.get('values', [])
        results[program_type] = arima_forecast(values, labels, periods=periods)
    return results
