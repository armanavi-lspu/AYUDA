# Timezone Implementation - Asia/Manila

## Overview
The system has been updated to properly handle timezone conversions. All timestamps are stored in UTC in the database but are displayed in Asia/Manila timezone (UTC+8) to match the local time.

## Changes Made

### 1. Configuration (`config.py`)
- Added `TIMEZONE` setting with default value `Asia/Manila`
- Created `TZ` attribute using `pytz` for timezone object
- Can be overridden via environment variable `TIMEZONE`

```python
TIMEZONE = os.environ.get('TIMEZONE', 'Asia/Manila')
TZ = pytz.timezone(TIMEZONE)
```

### 2. Models (`app/models.py`)
- Updated datetime imports to include `timezone` from `datetime`
- Created `get_utc_now()` helper function that returns timezone-aware UTC datetime
- Updated database column defaults to use timezone-aware datetime:
  - User.created_at
  - Programs.date
  - Announcements.created_at, updated_at
  - Applications.application_date
  - AdminActivityLog.created_at
  - UserActivityLog.created_at
  - And all other timestamp columns

```python
from datetime import datetime, timezone

def get_utc_now():
    """Get current UTC time as timezone-aware datetime"""
    return datetime.now(timezone.utc)
```

### 3. Activity Logger (`app/activity_logger.py`)
- Updated imports to include `timezone`
- Changed timestamp recording from `datetime.utcnow()` to `datetime.now(timezone.utc)`
- Ensures admin activity logs use timezone-aware UTC times

### 4. Application Initialization (`app/__init__.py`)
- Added timezone configuration to Flask app during initialization
- Makes timezone accessible throughout the application via `app.config['TZ']`

### 5. Date Formatting Utility (`app/utils.py`)
- Enhanced `format_date()` function to convert UTC times to local timezone
- Handles both naive and timezone-aware datetime objects
- Uses configured timezone (Asia/Manila) for display
- Includes error handling with fallback to UTC time

```python
def format_date(timestamp):
    """Format datetime for display in local timezone"""
    if not timestamp:
        return "N/A"
    if isinstance(timestamp, str):
        return timestamp
    
    try:
        # Get the configured timezone
        tz = current_app.config.get('TZ', pytz.timezone('Asia/Manila'))
        
        # Convert UTC timestamp to local timezone
        if timestamp.tzinfo is None:
            timestamp_utc = pytz.utc.localize(timestamp)
        else:
            timestamp_utc = timestamp
        
        timestamp_local = timestamp_utc.astimezone(tz)
        
        # Get current time in local timezone
        now_local = datetime.datetime.now(tz)
        
        # Calculate difference using local times
        diff = now_local - timestamp_local
        
        if diff.days == 0:
            return timestamp_local.strftime('%I:%M %p')
        elif diff.days < 7:
            return timestamp_local.strftime('%a, %I:%M %p')
        else:
            return timestamp_local.strftime('%b %d, %Y %I:%M %p')
    except Exception as e:
        print(f"Timezone conversion error: {e}")
        return str(timestamp)
```

## How It Works

1. **Storage**: All timestamps are stored in the database as UTC with timezone information
2. **Display**: When displaying timestamps (in activity logs, applications, etc.), the system:
   - Retrieves the UTC datetime from database
   - Converts it to Asia/Manila timezone using pytz
   - Formats it for display in the local timezone

## Verification

```python
# UTC Time: 2026-03-18 18:45:22 (UTC)
# Manila Time: 2026-03-19 02:45:22 (UTC+8)
# Time difference: +08:00 (as expected)
```

The activity logs now display times in Asia/Manila timezone, which is UTC+8.

## Changing the Timezone

To use a different timezone:

1. **Via environment variable**:
   ```powershell
   set TIMEZONE=America/New_York
   # Then restart the application
   ```

2. **Via config.py**:
   ```python
   TIMEZONE = 'Europe/London'  # Change default value
   TZ = pytz.timezone(TIMEZONE)
   ```

## Common Timezones
- `Asia/Manila` - Philippines (UTC+8) ✓ Current
- `Asia/Bangkok` - Thailand (UTC+7)
- `Asia/Tokyo` - Japan (UTC+9)
- `America/New_York` - EST/EDT (UTC-5/-4)
- `Europe/London` - GMT/BST (UTC+0/+1)
- `Australia/Sydney` - AEDT/AEST (UTC+11/+10)

## References
- Python `datetime.timezone` documentation
- `pytz` timezone library
- Flask `current_app.config` usage
