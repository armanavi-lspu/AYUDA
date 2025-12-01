"""
Tests for the ARIMA forecasting module.
"""
import pytest
from datetime import datetime
from app.forecasting import (
    arima_forecast,
    simple_linear_forecast,
    forecast_program_growth,
    prepare_time_series_data
)


class TestPrepareTimeSeriesData:
    """Tests for time series data preparation"""
    
    def test_prepare_with_valid_data(self):
        """Test preparing valid time series data"""
        labels = ['January 2024', 'February 2024', 'March 2024']
        values = [10, 15, 20]
        
        series = prepare_time_series_data(labels, values)
        
        assert series is not None
        assert len(series) == 3
        assert list(series.values) == [10, 15, 20]
    
    def test_prepare_with_short_month_format(self):
        """Test preparing data with short month format"""
        labels = ['Jan 2024', 'Feb 2024', 'Mar 2024']
        values = [5, 10, 15]
        
        series = prepare_time_series_data(labels, values)
        
        assert series is not None
        assert len(series) == 3
    
    def test_prepare_with_empty_data(self):
        """Test preparing empty data returns None"""
        series = prepare_time_series_data([], [])
        assert series is None
    
    def test_prepare_with_mismatched_lengths(self):
        """Test that mismatched lengths return None"""
        labels = ['January 2024', 'February 2024']
        values = [10, 15, 20]
        
        series = prepare_time_series_data(labels, values)
        assert series is None


class TestSimpleLinearForecast:
    """Tests for simple linear forecast fallback"""
    
    def test_linear_forecast_with_data(self):
        """Test linear forecast with valid data"""
        historical_data = [10, 15, 20, 25]
        historical_labels = ['Jan 2024', 'Feb 2024', 'Mar 2024', 'Apr 2024']
        
        result = simple_linear_forecast(historical_data, historical_labels, periods=3)
        
        assert result['success'] is True
        assert result['model'] == 'linear'
        assert len(result['forecast_values']) == 3
        assert len(result['forecast_labels']) == 3
        # Values should be increasing based on positive trend
        assert all(v >= 0 for v in result['forecast_values'])
    
    def test_linear_forecast_with_empty_data(self):
        """Test linear forecast with empty data"""
        result = simple_linear_forecast([], [], periods=3)
        
        assert result['success'] is False
        assert result['model'] == 'none'
        assert len(result['forecast_values']) == 0
    
    def test_linear_forecast_single_value(self):
        """Test linear forecast with single data point"""
        historical_data = [10]
        historical_labels = ['Jan 2024']
        
        result = simple_linear_forecast(historical_data, historical_labels, periods=3)
        
        assert result['success'] is True
        assert len(result['forecast_values']) == 3
    
    def test_linear_forecast_no_negative_values(self):
        """Test that forecast values are never negative"""
        # Decreasing trend that would go negative
        historical_data = [100, 50, 10, 2]
        historical_labels = ['Jan 2024', 'Feb 2024', 'Mar 2024', 'Apr 2024']
        
        result = simple_linear_forecast(historical_data, historical_labels, periods=6)
        
        assert all(v >= 0 for v in result['forecast_values'])


class TestArimaForecast:
    """Tests for ARIMA forecast function"""
    
    def test_arima_with_sufficient_data(self):
        """Test ARIMA forecast with sufficient data points"""
        # Need at least 3 data points for ARIMA
        historical_data = [10, 15, 20, 25, 30, 35]
        historical_labels = [
            'January 2024', 'February 2024', 'March 2024',
            'April 2024', 'May 2024', 'June 2024'
        ]
        
        result = arima_forecast(historical_data, historical_labels, periods=3)
        
        assert result['success'] is True
        assert len(result['forecast_values']) == 3
        assert len(result['forecast_labels']) == 3
        assert 'model' in result
    
    def test_arima_with_insufficient_data(self):
        """Test ARIMA falls back to linear with insufficient data"""
        historical_data = [10, 15]
        historical_labels = ['January 2024', 'February 2024']
        
        result = arima_forecast(historical_data, historical_labels, periods=3)
        
        assert result['success'] is True
        # Should fall back to linear model
        assert result['model'] == 'linear'
    
    def test_arima_no_negative_forecasts(self):
        """Test that ARIMA forecasts are never negative"""
        historical_data = [50, 40, 30, 20, 10, 5]
        historical_labels = [
            'January 2024', 'February 2024', 'March 2024',
            'April 2024', 'May 2024', 'June 2024'
        ]
        
        result = arima_forecast(historical_data, historical_labels, periods=6)
        
        assert all(v >= 0 for v in result['forecast_values'])
        if result.get('confidence_lower'):
            assert all(v >= 0 for v in result['confidence_lower'])
    
    def test_arima_with_empty_data(self):
        """Test ARIMA with empty data"""
        result = arima_forecast([], [], periods=3)
        
        # Should fall back to linear which handles empty data
        assert 'forecast_values' in result


class TestProgramGrowthForecast:
    """Tests for program category growth forecast"""
    
    def test_forecast_with_valid_data(self):
        """Test program growth forecast with valid data"""
        program_data = {
            'labels': ['Housing', 'Education', 'Healthcare'],
            'data': [100, 50, 75]
        }
        
        result = forecast_program_growth(program_data)
        
        assert result['success'] is True
        assert len(result['forecast_data']) == 3
        # Default 10% growth
        assert result['forecast_data'][0] == 110  # 100 * 1.10
        assert result['forecast_data'][1] == 55   # 50 * 1.10
        assert result['forecast_data'][2] == 82   # 75 * 1.10 = 82.5, rounded to 82
    
    def test_forecast_with_custom_growth_rate(self):
        """Test program growth forecast with custom growth rate"""
        program_data = {
            'labels': ['Housing'],
            'data': [100]
        }
        
        result = forecast_program_growth(program_data, growth_rate=0.25)
        
        assert result['success'] is True
        assert result['forecast_data'][0] == 125  # 100 * 1.25
        assert result['growth_rate'] == 0.25
    
    def test_forecast_with_empty_data(self):
        """Test program growth forecast with empty data"""
        result = forecast_program_growth(None)
        
        assert result['success'] is False
    
    def test_forecast_preserves_labels(self):
        """Test that labels are preserved in forecast"""
        program_data = {
            'labels': ['Type A', 'Type B'],
            'data': [10, 20]
        }
        
        result = forecast_program_growth(program_data)
        
        assert result['labels'] == ['Type A', 'Type B']