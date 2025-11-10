# Recommendation API Usage Guide

This document provides examples of how to use the recommendation system API endpoints in your Flask application.

## Available Endpoints

### 1. Get Recommendations for Current User
**Endpoint:** `GET /api/recommendations/for-user`  
**Authentication:** Required  
**Description:** Returns personalized program recommendations for the logged-in user based on their interaction history.

**Query Parameters:**
- `limit` (optional, default: 5, max: 20): Number of recommendations to return

**Example Request:**
```bash
curl -X GET "http://localhost:5000/api/recommendations/for-user?limit=5" \
  -H "Cookie: session=your_session_cookie"
```

**Example Response:**
```json
{
  "user_id": 123,
  "recommendations": [
    {
      "id": 5,
      "program_name": "Emergency Relief Fund",
      "program_type": "Emergency",
      "program_period": "Short-term",
      "description": "Quick access to emergency funds",
      "date": "2024-01-15T10:30:00"
    },
    {
      "id": 7,
      "program_name": "Medical Assistance Program",
      "program_type": "Healthcare",
      "program_period": "Long-term",
      "description": "Support for medical expenses",
      "date": "2024-01-20T14:20:00"
    }
  ],
  "count": 2
}
```

---

### 2. Get Similar Programs
**Endpoint:** `GET /api/recommendations/similar/<program_id>`  
**Authentication:** Required  
**Description:** Returns programs similar to a specific program based on content similarity.

**Path Parameters:**
- `program_id`: ID of the program to find similar programs for

**Query Parameters:**
- `limit` (optional, default: 5, max: 20): Number of similar programs to return

**Example Request:**
```bash
curl -X GET "http://localhost:5000/api/recommendations/similar/10?limit=3" \
  -H "Cookie: session=your_session_cookie"
```

**Example Response:**
```json
{
  "source_program": {
    "id": 10,
    "program_name": "Educational Scholarship",
    "program_type": "Education"
  },
  "similar_programs": [
    {
      "id": 12,
      "program_name": "Student Grant Program",
      "program_type": "Education",
      "program_period": "Long-term",
      "description": "Financial support for college students",
      "date": "2024-02-01T09:00:00"
    },
    {
      "id": 15,
      "program_name": "Vocational Training Fund",
      "program_type": "Education",
      "program_period": "Medium-term",
      "description": "Support for vocational education",
      "date": "2024-02-05T11:15:00"
    }
  ],
  "count": 2
}
```

---

### 3. Track User Interaction
**Endpoint:** `POST /api/recommendations/track-interaction`  
**Authentication:** Required  
**Description:** Records a user interaction with a program. This data is used to improve future recommendations.

**Request Body (JSON):**
```json
{
  "program_id": 10,
  "interaction_type": "view"
}
```

**Interaction Types:**
- `view`: User viewed the program details
- `bookmark`: User bookmarked/saved the program
- `apply`: User applied to the program

**Example Request:**
```bash
curl -X POST "http://localhost:5000/api/recommendations/track-interaction" \
  -H "Content-Type: application/json" \
  -H "Cookie: session=your_session_cookie" \
  -d '{
    "program_id": 10,
    "interaction_type": "apply"
  }'
```

**Example Response:**
```json
{
  "success": true,
  "message": "Interaction tracked successfully",
  "interaction": {
    "user_id": 123,
    "program_id": 10,
    "interaction_type": "apply"
  }
}
```

---

### 4. Get Popular Programs
**Endpoint:** `GET /api/recommendations/popular`  
**Authentication:** Not Required  
**Description:** Returns the most popular programs based on interaction count. Useful for cold start or anonymous users.

**Query Parameters:**
- `limit` (optional, default: 5, max: 20): Number of programs to return

**Example Request:**
```bash
curl -X GET "http://localhost:5000/api/recommendations/popular?limit=10"
```

**Example Response:**
```json
{
  "popular_programs": [
    {
      "id": 5,
      "program_name": "Emergency Financial Aid",
      "program_type": "Emergency",
      "program_period": "Short-term",
      "description": "Immediate financial assistance",
      "date": "2024-01-10T08:00:00",
      "interaction_count": 45
    },
    {
      "id": 12,
      "program_name": "Housing Assistance",
      "program_type": "Housing",
      "program_period": "Long-term",
      "description": "Help with housing costs",
      "date": "2024-01-15T10:30:00",
      "interaction_count": 38
    }
  ],
  "count": 2
}
```

---

## Integration Example (JavaScript)

### Fetch Recommendations on Page Load
```javascript
// Get personalized recommendations for logged-in user
async function loadRecommendations() {
  try {
    const response = await fetch('/api/recommendations/for-user?limit=5');
    const data = await response.json();
    
    if (data.recommendations) {
      displayRecommendations(data.recommendations);
    }
  } catch (error) {
    console.error('Error loading recommendations:', error);
  }
}

function displayRecommendations(recommendations) {
  const container = document.getElementById('recommendations-container');
  
  recommendations.forEach(program => {
    const card = `
      <div class="program-card">
        <h3>${program.program_name}</h3>
        <p class="program-type">${program.program_type} - ${program.program_period}</p>
        <p>${program.description}</p>
        <button onclick="viewProgram(${program.id})">View Details</button>
      </div>
    `;
    container.innerHTML += card;
  });
}
```

### Track User Interactions
```javascript
// Track when user views a program
async function viewProgram(programId) {
  // Track the view
  await fetch('/api/recommendations/track-interaction', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      program_id: programId,
      interaction_type: 'view'
    })
  });
  
  // Show program details
  window.location.href = `/programs/${programId}`;
}

// Track when user applies
async function applyToProgram(programId) {
  await fetch('/api/recommendations/track-interaction', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      program_id: programId,
      interaction_type: 'apply'
    })
  });
  
  // Continue with application
}

// Track when user bookmarks
async function bookmarkProgram(programId) {
  await fetch('/api/recommendations/track-interaction', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      program_id: programId,
      interaction_type: 'bookmark'
    })
  });
  
  // Update UI
}
```

### Load Similar Programs
```javascript
// Show similar programs on program detail page
async function loadSimilarPrograms(currentProgramId) {
  try {
    const response = await fetch(
      `/api/recommendations/similar/${currentProgramId}?limit=3`
    );
    const data = await response.json();
    
    if (data.similar_programs) {
      displaySimilarPrograms(data.similar_programs);
    }
  } catch (error) {
    console.error('Error loading similar programs:', error);
  }
}

function displaySimilarPrograms(programs) {
  const container = document.getElementById('similar-programs');
  
  programs.forEach(program => {
    const card = `
      <div class="similar-program-card">
        <h4>${program.program_name}</h4>
        <p>${program.program_type}</p>
        <a href="/programs/${program.id}">View Program</a>
      </div>
    `;
    container.innerHTML += card;
  });
}
```

---

## Python Integration Example

### Using in Flask Routes
```python
from flask import Blueprint, render_template
from flask_login import login_required, current_user
from app.recommendation import recommend_programs_for_user

programs_bp = Blueprint('programs', __name__)

@programs_bp.route('/dashboard')
@login_required
def dashboard():
    # Get personalized recommendations
    recommended_programs = recommend_programs_for_user(
        user_id=current_user.id,
        top_n=5
    )
    
    return render_template(
        'dashboard.html',
        recommendations=recommended_programs,
        user=current_user
    )
```

### Manual Interaction Tracking
```python
from app.models import UserProgramInteraction
from app import db

def track_program_view(user_id, program_id):
    """Track when a user views a program"""
    interaction = UserProgramInteraction(
        user_id=user_id,
        program_id=program_id,
        interaction_type='view'
    )
    db.session.add(interaction)
    db.session.commit()

def track_program_application(user_id, program_id):
    """Track when a user applies to a program"""
    interaction = UserProgramInteraction(
        user_id=user_id,
        program_id=program_id,
        interaction_type='apply'
    )
    db.session.add(interaction)
    db.session.commit()
```

---

## Error Responses

### 400 Bad Request
Missing or invalid request parameters.
```json
{
  "error": "Missing required fields: program_id, interaction_type"
}
```

### 401 Unauthorized
Authentication required but not provided.
```json
{
  "error": "Unauthorized"
}
```

### 404 Not Found
Program not found.
```json
{
  "error": "Program not found"
}
```

---

## Best Practices

1. **Track Interactions Consistently**: Always track user interactions (views, bookmarks, applications) to improve recommendation quality.

2. **Use Appropriate Interaction Types**: 
   - Track `view` for any program page visit
   - Track `bookmark` when user saves/favorites a program
   - Track `apply` when user submits an application

3. **Handle Cold Start**: Use the `/popular` endpoint for new users or anonymous visitors.

4. **Cache Recommendations**: Consider caching recommendations for a short period to reduce computation.

5. **Progressive Enhancement**: Show popular programs while loading personalized recommendations.

6. **Error Handling**: Always handle API errors gracefully in your UI.

---

## Testing the API

You can test the API endpoints using the provided test suite:

```bash
# Run all recommendation tests
pytest tests/test_recommendation.py tests/test_recommendation_api.py -v

# Run only API tests
pytest tests/test_recommendation_api.py -v
```

---

## Next Steps

- Integrate these endpoints into your frontend templates
- Add recommendation widgets to dashboard and program pages
- Implement analytics to track recommendation effectiveness
- Consider A/B testing different recommendation strategies
