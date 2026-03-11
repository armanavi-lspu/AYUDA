"""
Content-based beneficiary recommendation module using scikit-learn.
Uses TfidfVectorizer + ColumnTransformer + NearestNeighbors for 
finding similar beneficiaries based on their profiles.
"""

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.neighbors import NearestNeighbors
from sklearn.pipeline import Pipeline
import joblib
import os

# Age threshold for senior citizen classification (used in scoring and target profile)
SENIOR_CITIZEN_AGE = 60

# Model cache path (written after each fit for external monitoring; never read back)
_CACHE_PATH = 'instance/recommender_cache.pkl'

# Candidate selection tuning
MAX_NEIGHBORS = 50
CANDIDATE_MULTIPLIER = 3
# Minimum candidate pool size to maintain diversity after post-filtering; 30
# provides sufficient variety for typical recommendation requests of 10-20 items
MIN_CANDIDATE_POOL = 30


class BeneficiaryRecommender:
    """
    Content-based recommender for beneficiaries using nearest neighbors.
    """
    
    def __init__(self):
        self.model = None
        self.preprocessor = None
        self.beneficiary_data = None
        self.feature_names = ['age', 'family_annual_income', 'barangay', 
                              'is_solo_parent', 'is_student', 'is_pwd',
                              'is_currently_employed', 'occupation']
    
    def _prepare_dataframe(self, beneficiaries):
        """
        Convert list of beneficiary data to DataFrame for processing.
        
        Args:
            beneficiaries: List of dictionaries with beneficiary data
            
        Returns:
            pandas DataFrame with processed features
        """
        if not beneficiaries:
            return None
        
        df = pd.DataFrame(beneficiaries)
        
        # Fill missing values
        df['age'] = df['age'].fillna(0).astype(float)
        df['family_annual_income'] = df['family_annual_income'].fillna(0).astype(float)
        df['barangay'] = df['barangay'].fillna('Unknown')
        df['is_solo_parent'] = df['is_solo_parent'].fillna(False).astype(int)
        df['is_student'] = df['is_student'].fillna(False).astype(int)
        df['is_pwd'] = df['is_pwd'].fillna(False).astype(int)
        df['is_currently_employed'] = df['is_currently_employed'].fillna(False).astype(int)
        df['occupation'] = df['occupation'].fillna('None')
        
        return df
    
    def _create_preprocessor(self, df):
        """
        Create a ColumnTransformer for preprocessing beneficiary features.
        
        Args:
            df: DataFrame with beneficiary data
            
        Returns:
            ColumnTransformer for feature preprocessing
        """
        # Numerical features - standardize
        numerical_features = ['age', 'family_annual_income']
        
        # Categorical features - one-hot encode
        categorical_features = ['barangay']
        
        # Binary features - keep as is
        binary_features = ['is_solo_parent', 'is_student', 'is_pwd', 'is_currently_employed']
        
        # Text features - TF-IDF on occupation
        text_features = ['occupation']
        
        preprocessor = ColumnTransformer(
            transformers=[
                ('num', StandardScaler(), numerical_features),
                ('cat', OneHotEncoder(handle_unknown='ignore', sparse_output=False), categorical_features),
                ('bin', 'passthrough', binary_features),
                ('text', TfidfVectorizer(max_features=50, stop_words='english'), 'occupation')
            ],
            remainder='drop'
        )
        
        return preprocessor
    
    def fit(self, beneficiaries):
        """
        Fit the recommender model on beneficiary data.
        
        Args:
            beneficiaries: List of dictionaries with beneficiary data
            
        Returns:
            bool: True if fitting was successful, False otherwise
        """
        df = self._prepare_dataframe(beneficiaries)
        if df is None or len(df) < 1:
            return False
        
        self.beneficiary_data = df
        
        # Create and fit preprocessor
        self.preprocessor = self._create_preprocessor(df)
        
        # Transform features
        features = self.preprocessor.fit_transform(df)
        
        # Fit NearestNeighbors model with appropriate n_neighbors
        # Ensure n_neighbors is at least 1 and at most the number of samples
        n_neighbors = max(1, min(len(df), MAX_NEIGHBORS))
        self.model = NearestNeighbors(n_neighbors=n_neighbors, metric='cosine')
        self.model.fit(features)
        
        return True
    
    def recommend(self, target_profile, n_recommendations=10, filters=None):
        """
        Generate recommendations based on a target profile.
        
        Args:
            target_profile: Dictionary with target beneficiary characteristics
            n_recommendations: Number of recommendations to return
            filters: Dictionary with filter criteria to narrow results after KNN
            
        Returns:
            List of recommended beneficiaries with similarity scores
        """
        if self.model is None or self.beneficiary_data is None:
            return []
        
        # Prepare target profile
        target_df = self._prepare_dataframe([target_profile])
        if target_df is None:
            return []
        
        # Transform target
        target_features = self.preprocessor.transform(target_df)
        
        # Find nearest neighbors (request extra candidates to account for post-filtering removals),
        # capped to the neighbor count used when fitting the model. The minimum pool size preserves
        # diversity when subsequent filters discard matches.
        max_neighbors = getattr(self.model, 'n_neighbors', MAX_NEIGHBORS)
        n_candidates = min(
            len(self.beneficiary_data),
            max(n_recommendations * CANDIDATE_MULTIPLIER, MIN_CANDIDATE_POOL),
            max_neighbors
        )
        distances, indices = self.model.kneighbors(target_features, n_neighbors=n_candidates)
        
        # Convert distances to similarity scores (1 - cosine distance)
        similarities = 1 - distances[0]
        
        # Get recommendations, applying optional filters to narrow results
        recommendations = []
        for i, sim in zip(indices[0], similarities):
            if len(recommendations) >= n_recommendations:
                break
            
            rec = self.beneficiary_data.iloc[i].to_dict()

            # Apply filters dict if provided
            if filters:
                if 'barangay' in filters and rec.get('barangay') not in filters['barangay']:
                    continue
                if 'is_solo_parent' in filters and bool(rec.get('is_solo_parent')) != bool(filters['is_solo_parent']):
                    continue
                if 'is_student' in filters and bool(rec.get('is_student')) != bool(filters['is_student']):
                    continue
                if 'is_pwd' in filters and bool(rec.get('is_pwd')) != bool(filters['is_pwd']):
                    continue
                min_inc = filters.get('min_income')
                max_inc = filters.get('max_income')
                income = float(rec.get('family_annual_income', 0) or 0)
                if min_inc is not None and income < min_inc:
                    continue
                if max_inc is not None and income > max_inc:
                    continue

            rec['similarity_score'] = float(sim)

            # Build a score_breakdown that explains why this beneficiary
            # was matched, mirroring the rule-based breakdown structure.
            income = float(rec.get('family_annual_income', 0) or 0)
            target_income = float(target_profile.get('family_annual_income', 0) or 0)
            rec['score_breakdown'] = {
                'similarity_score': round(float(sim), 4),
                'income_score': round(max(0, 1 - abs(income - target_income) / max(target_income, 1)) * 0.3, 4) if target_income > 0 else 0,
                'solo_parent_bonus': 0.2 if rec.get('is_solo_parent') and target_profile.get('is_solo_parent') else 0,
                'student_bonus': 0.15 if rec.get('is_student') and target_profile.get('is_student') else 0,
                'pwd_bonus': 0.2 if rec.get('is_pwd') and target_profile.get('is_pwd') else 0,
                'senior_bonus': 0.15 if (rec.get('age') or 0) >= SENIOR_CITIZEN_AGE and (target_profile.get('age') or 0) >= SENIOR_CITIZEN_AGE else 0,
            }

            recommendations.append(rec)
        
        return recommendations

    def save_model(self, path='instance/recommender_cache.pkl'):
        """
        Persist the fitted model to disk using joblib.
        
        Args:
            path: File path to save the model cache
        """
        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else '.', exist_ok=True)
        joblib.dump({
            'model': self.model,
            'preprocessor': self.preprocessor,
            'beneficiary_data': self.beneficiary_data,
            'feature_names': self.feature_names
        }, path)

    @staticmethod
    def load_model(path='instance/recommender_cache.pkl'):
        """
        Load a previously saved model from disk.
        
        Args:
            path: File path to load the model cache from
            
        Returns:
            BeneficiaryRecommender instance if successful, None otherwise
        """
        try:
            data = joblib.load(path)
            recommender = BeneficiaryRecommender()
            recommender.model = data['model']
            recommender.preprocessor = data['preprocessor']
            recommender.beneficiary_data = data['beneficiary_data']
            recommender.feature_names = data.get('feature_names', recommender.feature_names)
            return recommender
        except Exception:
            return None
    
    def score_beneficiaries(self, beneficiaries, priority_weights=None):
        """
        Score beneficiaries based on priority weights and needs assessment.
        
        Args:
            beneficiaries: List of dictionaries with beneficiary data
            priority_weights: Dictionary with priority weights for different criteria
            
        Returns:
            List of beneficiaries with computed scores
        """
        if not beneficiaries:
            return []
        
        if priority_weights is None:
            priority_weights = {
                'low_income': 0.3,
                'solo_parent': 0.2,
                'student': 0.15,
                'pwd': 0.2,
                'senior_citizen': 0.15
            }
        
        scored_beneficiaries = []
        
        # Get income statistics for normalization
        incomes = [b.get('family_annual_income', 0) or 0 for b in beneficiaries]
        max_income = max(incomes) if incomes else 1
        min_income = min(incomes) if incomes else 0
        income_range = max_income - min_income if max_income > min_income else 1
        
        for b in beneficiaries:
            score = 0.0
            
            # Income score - lower income = higher score (with validation)
            try:
                income = float(b.get('family_annual_income', 0) or 0)
                # Validate and clamp income to valid range
                if income < 0:
                    income = 0
                elif income > 10000000:
                    income = 10000000
            except (ValueError, TypeError):
                income = 0
            
            income_score = 1 - ((income - min_income) / income_range) if income_range > 0 else 0.5
            score += priority_weights.get('low_income', 0.3) * income_score
            
            # Solo parent bonus
            if b.get('is_solo_parent'):
                score += priority_weights.get('solo_parent', 0.2)
            
            # Student bonus
            if b.get('is_student'):
                score += priority_weights.get('student', 0.15)
            
            # PWD bonus
            if b.get('is_pwd'):
                score += priority_weights.get('pwd', 0.2)
            
            # Senior citizen bonus (age >= SENIOR_CITIZEN_AGE)
            age = b.get('age', 0) or 0
            if age >= SENIOR_CITIZEN_AGE:
                score += priority_weights.get('senior_citizen', 0.15)
            
            b_copy = dict(b)
            b_copy['score'] = round(score, 4)
            # Score breakdown for transparency / API consumers
            b_copy['score_breakdown'] = {
                'income_score': round(income_score * priority_weights.get('low_income', 0.3), 4),
                'solo_parent_bonus': priority_weights.get('solo_parent', 0.2) if b.get('is_solo_parent') else 0,
                'student_bonus': priority_weights.get('student', 0.15) if b.get('is_student') else 0,
                'pwd_bonus': priority_weights.get('pwd', 0.2) if b.get('is_pwd') else 0,
                'senior_bonus': priority_weights.get('senior_citizen', 0.15) if (b.get('age') or 0) >= SENIOR_CITIZEN_AGE else 0,
            }
            scored_beneficiaries.append(b_copy)
        
        # Sort by score descending
        scored_beneficiaries.sort(key=lambda x: x['score'], reverse=True)
        
        return scored_beneficiaries


def get_recommendations(beneficiaries_data, target_profile=None, filters=None, max_beneficiaries=50,
                       solo_parent_priority=False, student_priority=False,
                       pwd_priority=False, senior_citizen_priority=False,
                       priority_barangays=None,
                       min_income=0, max_income=10000000):
    """
    Main function to generate beneficiary recommendations.

    When a target_profile is provided, the function uses the full ML pipeline
    (TF-IDF + OneHotEncoder + StandardScaler + NearestNeighbors) for content-based
    filtering (CBF).  The fitted model is cached on disk for one hour to avoid
    rebuilding on every call.

    When no target_profile is provided, the function falls back to rule-based
    priority scoring via score_beneficiaries() — preserving existing behaviour.
    
    Args:
        beneficiaries_data: List of beneficiary dictionaries
        target_profile: Optional dict with beneficiary-like fields used as the CBF
                        query vector.  If None, rule-based scoring is used instead.
        filters: Additional filter criteria passed into recommend() when using CBF
        max_beneficiaries: Maximum number of recommendations
        solo_parent_priority: Whether to prioritize solo parents
        student_priority: Whether to prioritize students
        pwd_priority: Whether to prioritize PWDs
        senior_citizen_priority: Whether to prioritize senior citizens (age >= 60)
        priority_barangays: List of barangays to filter by
        min_income: Minimum income filter (default: 0, max: 10,000,000)
        max_income: Maximum income filter (default: 10,000,000)
        
    Returns:
        List of recommended beneficiaries with scores
    """
    if not beneficiaries_data:
        return []
    
    # Validate income range parameters
    min_income = max(0, min(min_income, 10000000))  # Clamp between 0 and 10M
    max_income = max(0, min(max_income, 10000000))  # Clamp between 0 and 10M
    
    # Ensure min <= max
    if min_income > max_income:
        min_income, max_income = 0, 10000000  # Reset to defaults if invalid
    
    # Apply basic filters
    filtered = []
    for b in beneficiaries_data:
        try:
            income = float(b.get('family_annual_income', 0) or 0)
            
            # Validate income value
            if income < 0 or income > 10000000:
                income = 0  # Default to 0 if invalid
            
            # Income filter
            if income < min_income or income > max_income:
                continue
        except (ValueError, TypeError):
            # Skip if income cannot be converted to float
            continue
        
        # Barangay filter - if priority_barangays is provided, filter by them
        if priority_barangays and len(priority_barangays) > 0:
            barangay = b.get('barangay', '')
            if barangay not in priority_barangays:
                continue
        
        filtered.append(b)
    
    if not filtered:
        return []

    # --- Content-based filtering path (uses ML pipeline) ---
    # When a target_profile is given we fit NearestNeighbors on the current
    # filtered pool for each request.  The model is NOT loaded from cache here
    # because the filtered pool changes whenever a different program, income
    # range, or barangay selection is used — a stale cache would return the
    # same beneficiaries regardless of those changes.
    if target_profile is not None:
        recommender = BeneficiaryRecommender()
        fit_ok = recommender.fit(filtered)
        if not fit_ok:
            recommender = None
        else:
            # Save to cache as a warm-up snapshot (used by external tools /
            # monitoring only — never reloaded within this request path).
            try:
                recommender.save_model(_CACHE_PATH)
            except Exception:
                pass  # Cache write failure is non-fatal

        if recommender is not None:
            cbf_results = recommender.recommend(
                target_profile,
                n_recommendations=max_beneficiaries,
                filters=filters
            )
            if cbf_results:
                return cbf_results
        # If CBF produced no results (e.g. empty filtered pool), fall through to scoring

    # --- Rule-based scoring path (fallback or default) ---
    # Calculate priority weights based on user preferences
    priority_weights = {
        'low_income': 0.3,
        'solo_parent': 0.3 if solo_parent_priority else 0.1,
        'student': 0.2 if student_priority else 0.1,
        'pwd': 0.3 if pwd_priority else 0.1,
        'senior_citizen': 0.2 if senior_citizen_priority else 0.05,
    }
    
    # Normalize weights
    total_weight = sum(priority_weights.values())
    priority_weights = {k: v / total_weight for k, v in priority_weights.items()}
    
    # Create recommender and score beneficiaries
    recommender = BeneficiaryRecommender()
    scored = recommender.score_beneficiaries(filtered, priority_weights)
    
    # Return top N beneficiaries
    return scored[:max_beneficiaries]
