# Analytics and Forecasting Documentation

## Overview

The AYUDA analytics system provides comprehensive data visualization and forecasting capabilities for administrators to analyze application trends, program effectiveness, and make data-driven decisions.

## Features

### 1. Analytics Dashboard
- **Total Applications**: Total count of all applications
- **Unique Applicants**: Count of distinct users who have applied
- **Active Programs**: Number of programs available
- **Pending Review**: Applications awaiting review

### 2. Data Visualizations

#### Historical Analytics
- **Applicants Count Over Time**: Line chart showing monthly application trends
- **Applications per Program Type**: Pie/Doughnut chart showing distribution across program types
- **Applicants per Barangay**: Bar chart showing geographic distribution

#### Forecasting Models
- **Applicants Time Series Forecast**: Predicts future application volumes
- **Program Category Forecast**: Estimates demand for different program types

## Forecasting Methodology

### Exponential Smoothing
The forecasting model uses exponential smoothing, a statistical technique for time series forecasting that:

1. **Smooths Historical Data**: Reduces noise in historical data while giving more weight to recent observations
2. **Formula**: S_t = α * Y_t + (1 - α) * S_(t-1)
   - α (alpha) = 0.3 (smoothing parameter)
   - Y_t = actual value at time t
   - S_t = smoothed value at time t

### Trend Analysis
Linear regression is applied to identify trends:

1. **Trend Calculation**: Slope = (n*Σxy - Σx*Σy) / (n*Σx² - (Σx)²)
2. **Forecast Generation**: Forecast_t = Last_Value + (Trend * t)

### Growth Rate Estimation
For program categories, growth rates are estimated based on:
- Historical growth patterns
- Current application volumes
- Random variation (15-30% growth range)

## API Endpoints

### `/api/analytics/forecast-applicants`
**Method**: GET

**Parameters**:
- `months` (optional, default=12): Number of months of historical data to use
- `forecast_periods` (optional, default=6): Number of future periods to forecast

**Response**:
```json
{
  "success": true,
  "data": {
    "historical_labels": ["2024-01-01", ...],
    "historical_values": [10, 12, ...],
    "forecast_labels": ["2024-07-01", ...],
    "forecast_values": [25, 27, ...],
    "trend": 2.5
  },
  "message": "Forecast generated successfully"
}
```

### `/api/analytics/forecast-program-categories`
**Method**: GET

**Response**:
```json
{
  "success": true,
  "data": {
    "categories": ["Educational", "Health", ...],
    "current_values": [50, 30, ...],
    "forecast_values": [60, 38, ...]
  },
  "message": "Program category forecast generated successfully"
}
```

### `/api/analytics/applicants-timeseries`
**Method**: GET

**Parameters**:
- `months` (optional, default=12): Number of months to retrieve

**Response**:
```json
{
  "labels": ["January 2024", "February 2024", ...],
  "values": [10, 12, ...]
}
```

## Implementation Details

### Technologies Used
- **Backend**: Python Flask
- **Database**: PostgreSQL with SQLAlchemy ORM
- **Data Processing**: NumPy for numerical operations
- **Visualization**: Chart.js for frontend charts

### Key Functions

#### `exponential_smoothing(data, alpha=0.3)`
Applies exponential smoothing to time series data.

**Parameters**:
- `data`: List of numerical values
- `alpha`: Smoothing parameter (0 < α < 1)

**Returns**: List of smoothed values

#### `forecast_time_series(historical_data, periods=6)`
Generates forecasts using exponential smoothing and trend analysis.

**Parameters**:
- `historical_data`: List of tuples [(date_string, count), ...]
- `periods`: Number of future periods to forecast

**Returns**: Dictionary with historical and forecast data

### Database Schema

The analytics system uses the following main models:
- **Applications**: Application records with dates and status
- **Programs**: Program information including type
- **CommunityUsers**: User demographic information
- **Users**: Core user information

## Data Flow

1. **Data Collection**: Applications are stored in the database with timestamps
2. **Data Aggregation**: SQL queries aggregate data by month, program type, and location
3. **Data Serialization**: DateTime objects are converted to ISO format strings for JSON
4. **Frontend Rendering**: Chart.js renders interactive visualizations
5. **Forecast Generation**: API endpoints generate forecasts on-demand

## Best Practices

### For Developers
- Always handle empty datasets gracefully
- Ensure datetime serialization for JSON responses
- Use caching for expensive forecast calculations
- Validate input parameters on API endpoints

### For Administrators
- Review forecasts regularly for accuracy
- Compare forecasts with actual results to assess model performance
- Consider seasonal patterns when interpreting forecasts
- Use forecasts as guidance, not absolute predictions

## Future Enhancements

### Planned Features
1. **Machine Learning Models**: Integrate scikit-learn for more sophisticated forecasting
2. **Seasonal Decomposition**: Account for seasonal patterns in applications
3. **Confidence Intervals**: Add uncertainty bounds to forecasts
4. **Custom Date Ranges**: Allow users to select custom date ranges
5. **Export Functionality**: Export charts and data to PDF/Excel
6. **Real-time Updates**: WebSocket support for live data updates
7. **Advanced Filters**: Filter by program, status, demographics
8. **Anomaly Detection**: Identify unusual patterns in applications

### Model Improvements
1. **ARIMA/SARIMA**: More sophisticated time series models
2. **Prophet**: Facebook's forecasting tool for seasonal data
3. **Ensemble Methods**: Combine multiple models for better accuracy
4. **Cross-validation**: Validate model performance on historical data

## Troubleshooting

### Empty Graphs
**Symptom**: Charts show "No data available"
**Causes**:
- No applications in the database
- Date filtering excludes all data
- Database connection issues

**Solutions**:
- Check database for application records
- Adjust date range filter
- Verify database connection

### Forecast Errors
**Symptom**: Forecast charts show error messages
**Causes**:
- Insufficient historical data (< 2 data points)
- API endpoint errors
- Network connectivity issues

**Solutions**:
- Ensure at least 2-3 months of historical data
- Check browser console for API errors
- Verify server is running and accessible

### Performance Issues
**Symptom**: Slow chart loading
**Causes**:
- Large datasets
- Complex queries
- No database indexes

**Solutions**:
- Add database indexes on date columns
- Implement caching
- Use pagination for large datasets
- Consider data aggregation

## Support

For technical support or questions about the analytics system:
1. Check this documentation
2. Review the code comments in `app/admin/routes/analytics.py`
3. Test forecasting functions using `/tmp/test_forecasting.py`
4. Contact the development team

## Version History

### v1.1.0 (Current)
- Fixed empty graph issue by serializing datetime objects
- Implemented exponential smoothing forecasting model
- Added forecast API endpoints
- Integrated forecasts into analytics page
- Improved error handling and user feedback

### v1.0.0
- Initial analytics dashboard
- Basic charts (time series, pie, bar)
- Summary statistics
- Placeholder forecasts
