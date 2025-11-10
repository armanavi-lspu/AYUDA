# Program Recommendation System

## Overview

This document describes the recommendation algorithm implemented for recommending financial assistance programs to users in the FLASK application.

## Problem Statement

The system needs to recommend relevant financial assistance programs to users based on program characteristics and user interaction history.

## Algorithm Selection: Content-Based Filtering with TF-IDF

### Why Content-Based Filtering?

We chose **Content-Based Filtering using TF-IDF (Term Frequency-Inverse Document Frequency)** as the recommendation algorithm for the following reasons:

#### 1. **No Historical Data (Cold Start Problem)**
- **Challenge**: The system is new and doesn't have extensive user-item interaction history required for collaborative filtering.
- **Solution**: Content-based filtering works from day one by analyzing program attributes rather than requiring interaction data.

#### 2. **Rich Program Metadata**
- Programs have descriptive attributes:
  - `program_name`: Descriptive name of the program
  - `program_type`: Category (Emergency, Education, Business, Housing, etc.)
  - `program_period`: Duration (Short-term, Medium-term, Long-term)
  - `description`: Detailed description of the program
- Content-based filtering leverages this rich metadata effectively.

#### 3. **Cold Start Friendly**
- Works for **new users** without interaction history by recommending popular or recent programs
- Works for **new programs** immediately after creation based on similarity to existing programs

#### 4. **Interpretability**
- Recommendations can be explained: "We recommend this program because it is similar to programs you've shown interest in"
- Users can understand why they're seeing specific recommendations

#### 5. **Scalability**
- Efficient for small to medium-sized datasets
- Similarity matrix can be pre-computed and cached
- O(n) time complexity for recommendation generation after pre-computation

#### 6. **Context-Aware**
- Can incorporate different types of user interactions:
  - **Applications** (highest weight: 3.0) - Strong interest signal
  - **Bookmarks** (medium weight: 2.0) - Moderate interest signal
  - **Views** (low weight: 1.0) - Basic interest signal

## Algorithm Details

### Feature Extraction

The algorithm combines all program attributes into a single text representation:

```python
features = [
    program_name,
    program_type + " " + program_type,  # Type is repeated for higher weight
    program_period,
    description
]
combined_text = ' '.join(features)
```

### TF-IDF Vectorization

Uses scikit-learn's `TfidfVectorizer` with the following parameters:
- `max_features=100`: Limits vocabulary size for efficiency
- `stop_words='english'`: Removes common English words
- `ngram_range=(1, 2)`: Uses both single words and two-word phrases
- `min_df=1`: Includes terms that appear at least once

### Similarity Calculation

Computes cosine similarity between program vectors:
```python
similarity = cosine_similarity(program_features)
```

Cosine similarity ranges from 0 (completely different) to 1 (identical).

### Recommendation Process

1. **For users with interaction history**:
   - Retrieves all programs the user has interacted with
   - Finds similar programs for each interacted program
   - Weights similarities by interaction type (apply > bookmark > view)
   - Aggregates scores and ranks programs
   - Excludes already-interacted programs

2. **For new users (cold start)**:
   - Returns most popular programs (by interaction count)
   - Falls back to most recent programs if no interactions exist

## Implementation

### Core Components

1. **ProgramRecommender Class** (`app/recommendation.py`)
   - `fit(programs)`: Trains the model on available programs
   - `get_similar_programs(program_id, top_n)`: Finds similar programs
   - `recommend_for_user(user_id, top_n)`: Generates personalized recommendations

2. **UserProgramInteraction Model** (`app/models.py`)
   - Tracks user interactions with programs
   - Stores interaction type (view, bookmark, apply)
   - Records timestamp for temporal analysis

3. **Helper Functions**
   - `get_recommender()`: Factory function to create fitted recommender
   - `recommend_programs_for_user(user_id, top_n)`: High-level recommendation API

## Usage Example

```python
from app.recommendation import recommend_programs_for_user

# Get 5 recommended programs for a user
recommended_programs = recommend_programs_for_user(user_id=123, top_n=5)

for program in recommended_programs:
    print(f"- {program.program_name} ({program.program_type})")
```

## Future Enhancements

### Hybrid Approach
As the system accumulates data, consider adding:
- **Collaborative Filtering**: "Users similar to you also liked..."
- **Matrix Factorization**: Discover latent factors in user preferences

### Advanced Features
- **Temporal Decay**: Give more weight to recent interactions
- **Diversity**: Ensure recommendations span different program types
- **Personalization**: Incorporate user profile data (location, demographics)
- **A/B Testing**: Compare recommendation quality metrics

### Performance Optimization
- **Caching**: Cache similarity matrices and update periodically
- **Incremental Updates**: Update model when new programs are added
- **Batch Processing**: Pre-compute recommendations for all users

## Evaluation Metrics

To measure recommendation quality:
- **Precision@K**: Percentage of recommended programs that are relevant
- **Recall@K**: Percentage of relevant programs that are recommended
- **Click-Through Rate (CTR)**: Percentage of recommendations clicked
- **Conversion Rate**: Percentage of recommendations that lead to applications

## Dependencies

- `scikit-learn>=1.5.2`: TF-IDF vectorization and similarity calculation
- `pandas>=2.2.3`: Data manipulation
- `numpy>=2.1.3`: Numerical operations

## Testing

Comprehensive test suite in `tests/test_recommendation.py`:
- Recommender initialization and fitting
- Similar program identification
- User-based recommendations (with and without history)
- Content-based similarity validation
- Interaction type weighting

Run tests with:
```bash
pytest tests/test_recommendation.py -v
```

## Conclusion

Content-Based Filtering with TF-IDF is the optimal choice for this application because:
1. ✅ Works immediately without historical data
2. ✅ Leverages rich program metadata
3. ✅ Handles cold start for users and programs
4. ✅ Provides interpretable recommendations
5. ✅ Scales efficiently for the expected data size
6. ✅ Can evolve into a hybrid system as data grows

This approach provides a solid foundation for the recommendation system while remaining flexible for future enhancements.
