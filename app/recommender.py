"""
Content-based beneficiary recommendation module using scikit-learn.
Uses TfidfVectorizer + ColumnTransformer + NearestNeighbors for 
finding similar beneficiaries based on their profiles.
"""

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import RobustScaler, OneHotEncoder
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


# Need-focused ranking weights used for beneficiary ranking transparency.
NEED_FOCUSED_WEIGHTS = {
    'case_severity': 0.60,
    'income_vulnerability': 0.25,
    'household_vulnerability': 0.12,
    'repeat_beneficiary_penalty': 0.03,
}

NEED_FOCUSED_FACTOR_KEYS = tuple(NEED_FOCUSED_WEIGHTS.keys())


def _coerce_bool(value):
    """Convert common bool-like values into a boolean."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or '').strip().lower() in {'1', 'true', 'yes', 'y', 'on'}


def _resolve_need_focused_weights(scoring_parameters=None, scoring_weights=None):
    """Return active scoring weights with optional overrides and disabled factors set to zero."""
    active_weights = dict(NEED_FOCUSED_WEIGHTS)

    if isinstance(scoring_weights, dict):
        for factor_key in NEED_FOCUSED_FACTOR_KEYS:
            if factor_key in scoring_weights:
                try:
                    weight_value = float(scoring_weights.get(factor_key) or 0.0)
                except (TypeError, ValueError):
                    weight_value = 0.0
                active_weights[factor_key] = max(0.0, weight_value)

    if isinstance(scoring_parameters, dict):
        for factor_key in NEED_FOCUSED_FACTOR_KEYS:
            if factor_key in scoring_parameters and not _coerce_bool(scoring_parameters.get(factor_key)):
                active_weights[factor_key] = 0.0

    total_weight = sum(active_weights[factor_key] for factor_key in NEED_FOCUSED_FACTOR_KEYS)
    if total_weight > 0:
        active_weights = {
            factor_key: active_weights[factor_key] / total_weight
            for factor_key in NEED_FOCUSED_FACTOR_KEYS
        }

    return active_weights


def _case_severity_score(raw_severity):
    """Map case severity labels to a normalized score in [0, 1]."""
    label = str(raw_severity or '').strip().lower()
    if label in {'high', 'critical'}:
        return 1.0
    if label in {'medium', 'moderate'}:
        return 0.6
    if label == 'low':
        return 0.2
    # Neutral fallback for missing/unknown severities.
    return 0.4


def _income_vulnerability_score(raw_income):
    """Return vulnerability score where lower income means higher need."""
    try:
        income = float(raw_income or 0)
    except (TypeError, ValueError):
        income = 0.0

    if income <= 0:
        return 1.0
    if income < 100_000:
        return 1.0
    if income < 250_000:
        return 0.75
    if income < 400_000:
        return 0.50
    if income < 600_000:
        return 0.25
    return 0.10


def _household_vulnerability_score(beneficiary):
    """Compute a capped 0-1 household vulnerability score from profile indicators."""
    raw = 0.0

    if bool(beneficiary.get('is_solo_parent')):
        raw += 0.35
    if bool(beneficiary.get('is_student')):
        raw += 0.20
    if bool(beneficiary.get('is_pwd')):
        raw += 0.30

    age = beneficiary.get('age', 0) or 0
    try:
        age = float(age)
    except (TypeError, ValueError):
        age = 0.0
    if age >= SENIOR_CITIZEN_AGE:
        raw += 0.25

    is_employed = bool(beneficiary.get('is_currently_employed'))
    occupation = str(beneficiary.get('occupation') or '').strip().lower()
    occupation_keywords = {'laborer', 'farmer', 'vendor', 'driver', 'helper', 'cashier'}

    if not is_employed:
        raw += 0.25
    elif any(keyword in occupation for keyword in occupation_keywords):
        raw += 0.15

    return min(raw, 1.0)


def _parse_past_applications_count(past_apps):
    """Normalize past application history into a non-negative integer count."""
    if past_apps is None:
        return 0

    if isinstance(past_apps, (int, float)):
        return max(0, int(past_apps))

    if isinstance(past_apps, (list, tuple, set)):
        return len(past_apps)

    text = str(past_apps).strip()
    if not text:
        return 0

    if text.isdigit():
        return int(text)

    for delimiter in ('|', ';', ','):
        if delimiter in text:
            return len([part for part in text.split(delimiter) if part.strip()])

    # Non-empty history text implies at least one prior application signal.
    return 1


def _repeat_beneficiary_penalty(raw_past_applications):
    """Return repeat-beneficiary penalty in [-1.0, 0.0]."""
    past_apps = _parse_past_applications_count(raw_past_applications)
    if past_apps <= 0:
        return 0.0
    if past_apps == 1:
        return -0.3
    if past_apps == 2:
        return -0.6
    return -1.0


def _build_need_focused_breakdown(beneficiary, weights=None):
    """Build four-factor score breakdown aligned with the ranking formula."""
    active_weights = dict(NEED_FOCUSED_WEIGHTS)
    if isinstance(weights, dict):
        for factor_key in NEED_FOCUSED_FACTOR_KEYS:
            try:
                active_weights[factor_key] = float(weights.get(factor_key) or 0.0)
            except (TypeError, ValueError):
                active_weights[factor_key] = 0.0

    case_value = _case_severity_score(beneficiary.get('case_severity'))
    income_value = _income_vulnerability_score(beneficiary.get('family_annual_income'))
    household_value = _household_vulnerability_score(beneficiary)
    repeat_value = _repeat_beneficiary_penalty(
        beneficiary.get('past_applications_count', beneficiary.get('past_applications'))
    )

    case_contrib = active_weights['case_severity'] * case_value
    income_contrib = active_weights['income_vulnerability'] * income_value
    household_contrib = active_weights['household_vulnerability'] * household_value
    repeat_contrib = active_weights['repeat_beneficiary_penalty'] * repeat_value

    return {
        'case_severity_factor': {
            'label': 'Case Severity',
            'weight': active_weights['case_severity'],
            'beneficiary_value': round(case_value, 4),
            'contribution': round(case_contrib, 4),
        },
        'income_vulnerability_factor': {
            'label': 'Income Vulnerability',
            'weight': active_weights['income_vulnerability'],
            'beneficiary_value': round(income_value, 4),
            'contribution': round(income_contrib, 4),
        },
        'household_vulnerability_factor': {
            'label': 'Household Vulnerability',
            'weight': active_weights['household_vulnerability'],
            'beneficiary_value': round(household_value, 4),
            'contribution': round(household_contrib, 4),
        },
        'repeat_beneficiary_penalty_factor': {
            'label': 'Repeat Beneficiary Penalty',
            'weight': active_weights['repeat_beneficiary_penalty'],
            'beneficiary_value': round(repeat_value, 4),
            'contribution': round(repeat_contrib, 4),
        },
        # Legacy flat keys retained for compatibility with existing consumers.
        'severity_component': round(case_contrib, 4),
        'income_score': round(income_contrib, 4),
        'household_vulnerability_component': round(household_contrib, 4),
        'repeat_penalty_component': round(repeat_contrib, 4),
        'solo_parent_bonus': 0.0,
        'student_bonus': 0.0,
        'pwd_bonus': 0.0,
        'senior_bonus': 0.0,
    }


def _compute_need_focused_score(beneficiary, weights=None):
    """Compute final need-focused score and aligned breakdown."""
    breakdown = _build_need_focused_breakdown(beneficiary, weights=weights)
    score = (
        breakdown['case_severity_factor']['contribution']
        + breakdown['income_vulnerability_factor']['contribution']
        + breakdown['household_vulnerability_factor']['contribution']
        + breakdown['repeat_beneficiary_penalty_factor']['contribution']
    )
    return round(score, 4), breakdown


class BeneficiaryRecommender:
    """
    Content-based recommender for beneficiaries using nearest neighbors.
    """
    
    def __init__(self):
        self.model = None
        self.preprocessor = None
        self.beneficiary_data = None
        self.feature_names = ['age', 'family_annual_income', 'barangay',
                              'gender', 'disability_type',
                              'is_solo_parent', 'is_student', 'is_pwd',
                              'is_currently_employed', 'occupation', 'past_applications']
    
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

        def normalize_text_feature(value, prefix):
            """Return text with a guaranteed non-stopword anchor token."""
            text = '' if value is None else str(value).strip().lower()
            if text in ('', 'none', 'null', 'nan'):
                return f'{prefix}_none'
            return f'{prefix}_tag {text}'
        
        # Fill missing values
        df['age'] = df['age'].fillna(0).astype(float)
        df['family_annual_income'] = df['family_annual_income'].fillna(0).astype(float)
        df['barangay'] = df['barangay'].fillna('Unknown')
        df['is_solo_parent'] = df['is_solo_parent'].fillna(False).astype(int)
        df['is_student'] = df['is_student'].fillna(False).astype(int)
        df['is_pwd'] = df['is_pwd'].fillna(False).astype(int)
        df['is_currently_employed'] = df['is_currently_employed'].fillna(False).astype(int)
        # Keep a stable anchor token so TF-IDF never sees an empty vocabulary.
        if 'occupation' in df.columns:
            df['occupation'] = df['occupation'].apply(lambda x: normalize_text_feature(x, 'occupation'))
        else:
            df['occupation'] = 'occupation_none'
        df['gender'] = df['gender'].fillna('Unknown') if 'gender' in df.columns else 'Unknown'
        df['disability_type'] = df['disability_type'].fillna('None') if 'disability_type' in df.columns else 'None'
        if 'past_applications' in df.columns:
            df['past_applications'] = df['past_applications'].apply(lambda x: normalize_text_feature(x, 'history'))
        else:
            df['past_applications'] = 'history_none'

        # Compound vulnerability score (combines multiple risk factors)
        df['vulnerability_compound'] = (
            df['is_solo_parent'] * 0.30 +
            df['is_student'] * 0.20 +
            df['is_pwd'] * 0.30 +
            (1 - df['is_currently_employed']) * 0.20
        )

        return df
    
    def _create_preprocessor(self, df):
        """
        Create a ColumnTransformer for preprocessing beneficiary features.
        
        Args:
            df: DataFrame with beneficiary data
            
        Returns:
            ColumnTransformer for feature preprocessing
        """
        # Numerical features - RobustScaler handles income outliers better than StandardScaler
        numerical_features = ['age', 'family_annual_income', 'vulnerability_compound']

        # Categorical features - expanded with gender and disability type
        categorical_features = ['barangay', 'gender', 'disability_type']

        # Binary features - keep as is
        binary_features = ['is_solo_parent', 'is_student', 'is_pwd', 'is_currently_employed']

        # Text features - TF-IDF on occupation with bigrams for better semantic matching
        text_features = ['occupation']

        preprocessor = ColumnTransformer(
            transformers=[
                ('num', RobustScaler(), numerical_features),
                ('cat', OneHotEncoder(handle_unknown='ignore', sparse_output=False), categorical_features),
                ('bin', 'passthrough', binary_features),
                ('text', TfidfVectorizer(max_features=100, stop_words='english', ngram_range=(1, 2)), 'occupation'),
                ('past_apps', TfidfVectorizer(max_features=50, stop_words='english'), 'past_applications'),
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
                if 'municipality' in filters:
                    rec_municipality = str(rec.get('municipality') or '').strip().lower()
                    filter_municipality = str(filters['municipality'] or '').strip().lower()
                    if filter_municipality and rec_municipality != filter_municipality:
                        continue
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

            # Skip beneficiaries with zero or negative cosine similarity —
            # they have no meaningful alignment with the target program profile.
            if sim <= 0:
                continue

            rec['similarity_score'] = float(sim)

            # Build a score_breakdown that explains why this beneficiary
            # was matched, mirroring the rule-based breakdown structure.
            income = float(rec.get('family_annual_income', 0) or 0)
            target_income = float(target_profile.get('family_annual_income', 0) or 0)
            
            # Case severity score mapper
            severity = (rec.get('case_severity') or 'unrated').lower()
            severity_scores = {
                'critical': 1.0,
                'high': 0.8,
                'moderate': 0.6,
                'low': 0.4,
                'unrated': 0.0,
            }
            severity_score = severity_scores.get(severity, 0.0)
            
            rec['score_breakdown'] = {
                'severity_component': round(severity_score * 0.5, 4),  # 50% weight
                'similarity_score': round(float(sim), 4),
                'income_score': round(max(0, 1 - abs(income - target_income) / max(target_income, 1)) * 0.2, 4) if target_income > 0 else 0,
                # Identity-group bonuses are intentionally disabled; priority groups are enforced via filters.
                'solo_parent_bonus': 0.0,
                'student_bonus': 0.0,
                'pwd_bonus': 0.0,
                'senior_bonus': 0.0,
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
    
    def score_beneficiaries(self, beneficiaries, priority_weights=None, scoring_parameters=None, scoring_weights=None):
        """
        Score beneficiaries using the finalized need-focused formula.
        
        Args:
            beneficiaries: List of dictionaries with beneficiary data
            priority_weights: Dictionary with priority weights for different criteria
            
        Returns:
            List of beneficiaries with computed scores
        """
        if not beneficiaries:
            return []

        effective_weights = _resolve_need_focused_weights(
            scoring_parameters=scoring_parameters,
            scoring_weights=scoring_weights,
        )
        scored_beneficiaries = []

        for b in beneficiaries:
            score, breakdown = _compute_need_focused_score(b, weights=effective_weights)

            b_copy = dict(b)
            b_copy['score'] = score
            b_copy['score_breakdown'] = breakdown
            scored_beneficiaries.append(b_copy)
        
        # Sort by score descending
        scored_beneficiaries.sort(key=lambda x: x['score'], reverse=True)
        
        return scored_beneficiaries

    def recommend_hybrid(self, target_profile, n_recommendations=10,
                         similarity_weight=0.4, score_weight=0.6,
                         priority_weights=None):
        """Hybrid recommendation combining content similarity + need-based scoring.

        Args:
            target_profile: Dictionary with target beneficiary characteristics
            n_recommendations: Number of recommendations to return
            similarity_weight: Weight for similarity component (0-1)
            score_weight: Weight for need score component (0-1)
            priority_weights: Optional dict of priority weights for scoring

        Returns:
            List of ranked recommendations with hybrid scores
        """
        if self.model is None or self.beneficiary_data is None:
            return []

        # 1. Find similar profiles via KNN
        similar = self._find_similar_profiles(target_profile, n_recommendations * 3)
        if not similar:
            return []

        # 2. Score them based on need
        scored = self.score_beneficiaries(similar, priority_weights)
        if not scored:
            return similar[:n_recommendations]

        # 3. Normalize and combine scores
        max_score = max((s['score'] for s in scored), default=1) or 1
        hybrid_ranked = []
        for item in scored:
            similarity = 1 - item.get('similarity_distance', 1.0)
            need_normalized = item['score'] / max_score

            hybrid_score = (
                similarity_weight * max(0, similarity)
                + score_weight * need_normalized
            )

            item['hybrid_score'] = round(hybrid_score, 4)
            item['similarity_component'] = round(max(0, similarity), 4)
            item['need_component'] = round(need_normalized, 4)
            hybrid_ranked.append(item)

        hybrid_ranked.sort(key=lambda x: x['hybrid_score'], reverse=True)
        return hybrid_ranked[:n_recommendations]

    def _find_similar_profiles(self, target_profile, n_similar):
        """Find similar beneficiaries using the fitted NearestNeighbors model."""
        if self.model is None:
            return []

        target_df = self._prepare_dataframe([target_profile])
        if target_df is None:
            return []

        target_features = self.preprocessor.transform(target_df)

        max_neighbors = getattr(self.model, 'n_neighbors', MAX_NEIGHBORS)
        k = min(n_similar, len(self.beneficiary_data), max_neighbors)
        distances, indices = self.model.kneighbors(target_features, n_neighbors=k)

        similar = []
        for idx, distance in zip(indices[0], distances[0]):
            beneficiary = self.beneficiary_data.iloc[idx].to_dict()
            beneficiary['similarity_distance'] = float(distance)
            similar.append(beneficiary)

        return similar


def _parse_priority_group_tokens(priority_groups):
    """Parse a comma-separated priority groups string into normalized tokens."""
    if not priority_groups:
        return []
    return [t.strip().lower() for t in str(priority_groups).split(',') if t.strip()]


def _token_is_student(token):
    return 'student' in token


def _token_is_solo_parent(token):
    return 'solo parent' in token or 'solo_parent' in token or 'single parent' in token


def _token_is_pwd(token):
    return 'pwd' in token or 'disabilit' in token


def _token_is_senior(token):
    return 'senior' in token or 'elderly' in token


def _token_is_low_income(token):
    return 'low income' in token or 'indigent' in token


def _token_is_unemployed(token):
    return 'not employed' in token or 'unemployed' in token


def _parse_priority_groups(priority_groups):
    """
    Parse a comma-separated priority groups string into individual priority flags.
    
    Args:
        priority_groups: String like "Solo Parent, Student, PWD, Senior Citizen" or None
        
    Returns:
        Tuple of (solo_parent_priority, student_priority, pwd_priority, senior_citizen_priority)
    """
    tokens = _parse_priority_group_tokens(priority_groups)
    if not tokens:
        return False, False, False, False
    
    solo_parent = any(_token_is_solo_parent(token) for token in tokens)
    student = any(_token_is_student(token) for token in tokens)
    pwd = any(_token_is_pwd(token) for token in tokens)
    senior = any(_token_is_senior(token) for token in tokens)
    
    return solo_parent, student, pwd, senior


def _beneficiary_matches_priority_groups(beneficiary, priority_groups):
    """
        Return True if beneficiary satisfies all active strict priority constraints.

        Strict behavior:
        - If identity groups are selected (student/solo parent/PWD/senior),
            beneficiary must match at least one selected identity group.
        - If low-income/indigent groups are selected, beneficiary must satisfy
            the low-income threshold.
        - If unemployed groups are selected, beneficiary must be unemployed.
        - If no known enforceable groups are present, return False.
    """
    tokens = _parse_priority_group_tokens(priority_groups)
    if not tokens:
        return True

    age = float(beneficiary.get('age', 0) or 0)
    income = float(beneficiary.get('family_annual_income', 0) or 0)
    is_student = bool(beneficiary.get('is_student'))
    is_solo_parent = bool(beneficiary.get('is_solo_parent'))
    is_pwd = bool(beneficiary.get('is_pwd'))
    is_employed = bool(beneficiary.get('is_currently_employed'))

    identity_checks = []
    requires_low_income = False
    requires_unemployed = False

    for token in tokens:
        if _token_is_student(token):
            identity_checks.append(is_student)
        elif _token_is_solo_parent(token):
            identity_checks.append(is_solo_parent)
        elif _token_is_pwd(token):
            identity_checks.append(is_pwd)
        elif _token_is_senior(token):
            identity_checks.append(age >= SENIOR_CITIZEN_AGE)
        elif _token_is_low_income(token):
            requires_low_income = True
        elif _token_is_unemployed(token):
            requires_unemployed = True

    has_enforceable_group = bool(identity_checks) or requires_low_income or requires_unemployed
    if not has_enforceable_group:
        return False

    if identity_checks and not any(identity_checks):
        return False

    if requires_low_income and income > 250000:
        return False

    if requires_unemployed and is_employed:
        return False

    return True


def _apply_severity_boost(recommendations, case_severity_prioritization):
    """
    Severity is now integrated into base scoring (50% weight).
    This function is retained for backwards compatibility but doesn't apply
    additional multipliers since severity is already the primary criterion.
    """
    # Severity is already part of score_beneficiaries() scoring with 50% weight
    # No additional boost needed
    return recommendations


def get_recommendations(beneficiaries_data, target_profile=None, filters=None, max_beneficiaries=50,
                       solo_parent_priority=False, student_priority=False,
                       pwd_priority=False, senior_citizen_priority=False,
                       priority_barangays=None,
                       priority_municipality=None,
                       priority_groups=None,
                       min_income=0, max_income=10000000,
                       case_severity_prioritization=False,
                       scoring_parameters=None,
                       scoring_weights=None):
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
        priority_municipality: Municipality to strictly filter by
        priority_groups: Comma-separated string of priority groups (e.g., "Solo Parent, Student, PWD")
                        Overrides individual priority flags if provided and acts as
                        a hard profile filter on returned beneficiaries
        min_income: Minimum income filter (default: 0, max: 10,000,000)
        max_income: Maximum income filter (default: 10,000,000)
        case_severity_prioritization: If True, boost scores for higher severity cases
        scoring_parameters: Optional dict to enable/disable scoring factors
        scoring_weights: Optional dict to override scoring factor weights
        
    Returns:
        List of recommended beneficiaries with scores
    """
    # Parse priority_groups string if provided (takes precedence over individual flags)
    if priority_groups:
        solo_parent_priority, student_priority, pwd_priority, senior_citizen_priority = _parse_priority_groups(priority_groups)
    
    if not beneficiaries_data:
        return []
    
    # Validate income range parameters
    min_income = max(0, min(min_income, 10000000))  # Clamp between 0 and 10M
    max_income = max(0, min(max_income, 10000000))  # Clamp between 0 and 10M
    
    # Ensure min <= max
    if min_income > max_income:
        min_income, max_income = 0, 10000000  # Reset to defaults if invalid

    normalized_priority_municipality = str(priority_municipality or '').strip().lower() or None
    normalized_priority_barangays = {
        str(barangay).strip().lower()
        for barangay in (priority_barangays or [])
        if str(barangay).strip()
    }
    
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
        
        # Municipality filter - strict when provided.
        if normalized_priority_municipality:
            municipality = str(b.get('municipality') or '').strip().lower()
            if municipality != normalized_priority_municipality:
                continue

        # Barangay filter - if priority_barangays is provided, filter by them.
        if normalized_priority_barangays:
            barangay = str(b.get('barangay') or '').strip().lower()
            if barangay not in normalized_priority_barangays:
                continue

        # Priority-group profile filter - enforce only matching profiles when configured
        if priority_groups and not _beneficiary_matches_priority_groups(b, priority_groups):
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
                # Final hard guards to ensure strict compliance with active filters.
                if priority_groups:
                    cbf_results = [
                        rec for rec in cbf_results
                        if _beneficiary_matches_priority_groups(rec, priority_groups)
                    ]

                if normalized_priority_municipality:
                    cbf_results = [
                        rec for rec in cbf_results
                        if str(rec.get('municipality') or '').strip().lower() == normalized_priority_municipality
                    ]

                if normalized_priority_barangays:
                    cbf_results = [
                        rec for rec in cbf_results
                        if str(rec.get('barangay') or '').strip().lower() in normalized_priority_barangays
                    ]

                # Apply severity boost if enabled
                if case_severity_prioritization:
                    cbf_results = _apply_severity_boost(cbf_results, case_severity_prioritization)
                return cbf_results[:max_beneficiaries]
        # If CBF produced no results (e.g. empty filtered pool), fall through to scoring

    # --- Rule-based scoring path (fallback or default) ---
    # Identity-group priority bonuses are intentionally disabled;
    # program priority groups act as pre-selection filters.
    priority_weights = {
        'case_severity': 0.5,
        'low_income': 0.2,
    }
    
    # Create recommender and score beneficiaries
    recommender = BeneficiaryRecommender()
    scored = recommender.score_beneficiaries(
        filtered,
        priority_weights,
        scoring_parameters=scoring_parameters,
        scoring_weights=scoring_weights,
    )
    
    # Apply severity boost if enabled
    if case_severity_prioritization:
        scored = _apply_severity_boost(scored, case_severity_prioritization)

    if priority_groups:
        scored = [
            rec for rec in scored
            if _beneficiary_matches_priority_groups(rec, priority_groups)
        ]

    if normalized_priority_municipality:
        scored = [
            rec for rec in scored
            if str(rec.get('municipality') or '').strip().lower() == normalized_priority_municipality
        ]

    if normalized_priority_barangays:
        scored = [
            rec for rec in scored
            if str(rec.get('barangay') or '').strip().lower() in normalized_priority_barangays
        ]
    
    # Return top N beneficiaries
    return scored[:max_beneficiaries]
