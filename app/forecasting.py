"""
Forecasting module using ARIMA (AutoRegressive Integrated Moving Average) model.
This module provides stable time series forecasting for application trends.
"""

import numpy as np
import pandas as pd
from datetime import datetime
import warnings

# Suppress warnings from statsmodels during model fitting
warnings.filterwarnings('ignore', category=UserWarning)
warnings.filterwarnings('ignore', category=FutureWarning)

# Constants for simple linear forecast confidence intervals
CONFIDENCE_LOWER_MULTIPLIER = 0.8
CONFIDENCE_UPPER_MULTIPLIER = 1.2


def prepare_time_series_data(labels, values):
    """
    Prepare time series data for ARIMA model.
    
    Args:
        labels: List of date labels (strings like 'January 2024')
        values: List of numeric values corresponding to each label
        
    Returns:
        pandas Series with datetime index
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
    series = series.sort_index()
    
    return series


def arima_forecast(historical_data, historical_labels, periods=6):
    """
    Generate forecasts using ARIMA model.
    
    Args:
        historical_data: List of historical values
        historical_labels: List of date labels for historical data
        periods: Number of future periods to forecast (default: 6)
        
    Returns:
        dict with forecast_labels, forecast_values, confidence_lower, confidence_upper
    """
    try:
        from statsmodels.tsa.arima.model import ARIMA
    except ImportError:
        # Fallback to simple linear forecast if statsmodels is not available
        return simple_linear_forecast(historical_data, historical_labels, periods)
    
    # Need at least 3 data points for ARIMA
    if not historical_data or len(historical_data) < 3:
        return simple_linear_forecast(historical_data, historical_labels, periods)
    
    # Prepare time series
    series = prepare_time_series_data(historical_labels, historical_data)
    
    if series is None:
        return simple_linear_forecast(historical_data, historical_labels, periods)
    
    try:
        # Fit ARIMA model with order (1, 1, 1) - a commonly stable configuration
        # p=1: One autoregressive term
        # d=1: First-order differencing for stationarity
        # q=1: One moving average term
        model = ARIMA(series, order=(1, 1, 1))
        fitted_model = model.fit()
        
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
        
        return {
            'forecast_labels': forecast_labels,
            'forecast_values': forecast_values,
            'confidence_lower': confidence_lower,
            'confidence_upper': confidence_upper,
            'model': 'ARIMA(1,1,1)',
            'success': True
        }
        
    except Exception as e:
        # If ARIMA fails, fall back to simpler forecast
        return simple_linear_forecast(historical_data, historical_labels, periods)


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
    
    # Generate forecast labels using proper month arithmetic
    forecast_labels = []
    now = datetime.now()
    for i in range(1, periods + 1):
        next_date = now + pd.DateOffset(months=i)
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