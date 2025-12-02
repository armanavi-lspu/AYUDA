# Recommendation Algorithm Documentation

This document describes the recommendation algorithms used in the system.

## Overview

The system provides two types of recommendations:

1. **Beneficiary Recommendations** (`BeneficiaryRecommender`): Recommends community users (beneficiaries) to admins for program targeting
2. **Program Recommendations** (`ProgramRecommender`): Recommends programs to users based on their interactions and profile

---

## Beneficiary Recommender

The `BeneficiaryRecommender` class uses content-based filtering to recommend beneficiaries for government assistance programs.

### Features Used
- Age
- Family annual income
- Barangay (location)
- Solo parent status
- Student status
- PWD (Person with Disability) status
- Employment status
- Occupation

### Scoring System
Beneficiaries are scored based on configurable priority weights:
- `low_income`: Weight for income-based scoring (lower income = higher score)
- `solo_parent`: Bonus for solo parents
- `student`: Bonus for students
- `pwd`: Bonus for PWD
- `unemployed`: Bonus for unemployed individuals

---

## Program Recommender

The `ProgramRecommender` class uses content-based filtering with TF-IDF vectorization to recommend programs to users.

### How It Works

1. **Fitting**: The recommender fits a TF-IDF vectorizer on program texts (name, type, description)
2. **Recommendation**: Based on user interaction history or profile, generates personalized program recommendations

### Recommendation Paths

#### 1. Interaction-Based (Users with History)
For users who have applied to programs before:
- Builds an aggregate vector from previously interacted programs
- Computes cosine similarity with all programs
- Excludes already-interacted programs
- Returns top N most similar programs

#### 2. Cold Start with User Parameters (New Feature)
For users with no interaction history:
- Uses user profile data (income, status flags) to build recommendations
- Combines TF-IDF similarity with popularity and status-based boosts

---

## Cold Start with User Parameters

### Overview
The cold-start recommendation path addresses the "cold start problem" for new users who have no application history. Instead of relying solely on popularity, the system now uses user profile parameters to provide personalized recommendations.

### User Profile Construction

The system builds a text-based profile from the following `CommunityUsers` fields:

1. **Income Bucket Token**
   - `low_income`: Annual income ≤ 100,000
   - `mid_income`: Annual income ≤ 300,000
   - `high_income`: Annual income > 300,000
   - `unknown_income`: Missing or invalid income data

2. **Status Tokens**
   - `student` + `education`: If `is_student = True`
   - `solo_parent` + `emergency` + `housing`: If `is_solo_parent = True`
   - `pwd` + `healthcare`: If `is_pwd = True`
   - `unemployed` + `employment` + `business` + `emergency`: If not currently employed
   - `informal_worker` + `business` + `emergency`: If `is_informal_worker = True` (optional field)

### Example Profile Text
For a low-income student who is a solo parent:
```
"low_income student education solo_parent emergency housing"
```

### Scoring Algorithm

The final score for each program is computed as:

```
score = α × similarity + β × popularity + boost
```

Where:
- **α (ALPHA)** = 0.7 (weight for profile similarity)
- **β (BETA)** = 0.3 (weight for popularity)
- **boost** = status-to-type alignment bonus

### Similarity Calculation
1. Transform user profile text using the same TF-IDF vectorizer fitted on programs
2. Compute cosine similarity between user vector and all program vectors
3. Normalize similarities to 0..1 range

### Popularity Calculation
- Uses program recency/position as proxy for popularity
- First programs in the list are considered more popular
- Normalized to 0..1 range

### Status-to-Type Boosts

Small additive boosts are applied when user statuses align with program types:

| User Status | Program Type | Boost |
|-------------|--------------|-------|
| Student | Education | +0.15 |
| Solo Parent | Emergency | +0.10 |
| Solo Parent | Housing | +0.10 |
| Solo Parent | Healthcare | +0.10 |
| PWD | Healthcare | +0.10 |
| PWD | Employment | +0.10 |
| Unemployed | Employment | +0.10 |
| Unemployed | Business | +0.10 |
| Unemployed | Emergency | +0.10 |
| Informal Worker | Business | +0.05 |
| Informal Worker | Emergency | +0.05 |
| Low Income | Emergency | +0.10 |
| Low Income | Housing | +0.10 |

### Safe Field Handling

The implementation uses `getattr()` with default values to safely handle optional fields:
- `is_pwd`
- `is_unemployed`
- `is_informal_worker`

This ensures the system works correctly even if these fields are not present in the database schema.

### Fallback Behavior

The cold-start path has multiple fallback levels:

1. **Profile + Similarity**: If user has a CommunityUsers profile and TF-IDF works
2. **Popularity Only**: If profile is missing or TF-IDF fails
3. **Empty Results**: If no programs are available

### Control Flow

```
recommend_for_user(user_id)
    │
    ├─ Has interactions? ──Yes──> Interaction-based recommendations
    │                              (existing behavior unchanged)
    │
    └─ No (Cold Start)
           │
           ├─ Has CommunityUsers profile? ──Yes──> Profile-based cold start
           │                                        (new enhanced path)
           │
           └─ No ──> Popularity fallback
                     (existing behavior)
```

### API Compatibility

The `recommend_for_user()` method maintains full backward compatibility:
- Same input parameters
- Same output format (list of program dicts with 'score' key)
- No changes to existing behavior for users with interactions
- Optional callback functions for fetching profile and interactions

---

## Configuration

### Class-Level Constants (ProgramRecommender)

```python
# Blending weights
ALPHA = 0.7   # Weight for profile similarity
BETA = 0.3    # Weight for popularity

# TF-IDF configuration
TFIDF_MAX_FEATURES = 200

# Income bucket thresholds
INCOME_LOW_THRESHOLD = 100000    # ≤ 100k = low_income
INCOME_MID_THRESHOLD = 300000    # ≤ 300k = mid_income, > 300k = high_income

# Status-to-type boost values
BOOST_STUDENT_EDUCATION = 0.15
BOOST_SOLO_PARENT_EMERGENCY = 0.10
BOOST_SOLO_PARENT_HOUSING = 0.10
BOOST_SOLO_PARENT_HEALTHCARE = 0.10
BOOST_PWD_HEALTHCARE = 0.10
BOOST_PWD_EMPLOYMENT = 0.10
BOOST_UNEMPLOYED_EMPLOYMENT = 0.10
BOOST_UNEMPLOYED_BUSINESS = 0.10
BOOST_UNEMPLOYED_EMERGENCY = 0.10
BOOST_INFORMAL_WORKER_BUSINESS = 0.05
BOOST_INFORMAL_WORKER_EMERGENCY = 0.05
BOOST_LOW_INCOME_EMERGENCY = 0.10
BOOST_LOW_INCOME_HOUSING = 0.10
```

These can be adjusted for tuning without changing the algorithm structure.

---

## Usage Example

```python
from app.recommender import ProgramRecommender

# Initialize and fit
recommender = ProgramRecommender()
programs = [
    {'id': 1, 'program_name': 'Education Grant', 'program_type': 'Education', 'description': '...'},
    {'id': 2, 'program_name': 'Emergency Aid', 'program_type': 'Emergency', 'description': '...'},
    # ... more programs
]
recommender.fit(programs)

# Get recommendations for a cold-start user
user_profile = {
    'family_annual_income': 50000,  # low income
    'is_student': True,
    'is_solo_parent': False,
    'is_pwd': False,
    'is_currently_employed': False
}

recommendations = recommender.recommend_for_user(
    user_id=123,
    top_n=5,
    interactions=[],  # No interactions = cold start
    profile=user_profile
)

# Returns list of programs sorted by score
# Student profile will boost Education programs
```

---

## Testing

The recommendation algorithm is tested in `tests/test_recommender.py`:

- `TestProgramRecommender`: Basic functionality tests
- `TestColdStartRecommendations`: Cold-start specific tests including:
  - `test_cold_start_student_biases_towards_education`
  - `test_cold_start_solo_parent_low_income_biases_towards_emergency_or_housing`
  - `test_cold_start_pwd_biases_towards_healthcare`
  - `test_cold_start_unemployed_biases_towards_employment`

Run tests with:
```bash
python -m pytest tests/test_recommender.py -v
```
