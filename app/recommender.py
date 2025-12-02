"""
Content-based recommendation module using scikit-learn.

This module provides:
1. BeneficiaryRecommender: Recommends beneficiaries (users) for programs to admins
2. ProgramRecommender: Recommends programs to users based on interactions and profile

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
from sklearn.metrics.pairwise import cosine_similarity
import joblib
import os


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
        n_neighbors = max(1, min(len(df), 50))
        self.model = NearestNeighbors(n_neighbors=n_neighbors, metric='cosine')
        self.model.fit(features)
        
        return True
    
    def recommend(self, target_profile, n_recommendations=10, filters=None):
        """
        Generate recommendations based on a target profile.
        
        Args:
            target_profile: Dictionary with target beneficiary characteristics
            n_recommendations: Number of recommendations to return
            filters: Dictionary with filter criteria
            
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
        
        # Find nearest neighbors
        distances, indices = self.model.kneighbors(target_features)
        
        # Convert distances to similarity scores (1 - cosine distance)
        similarities = 1 - distances[0]
        
        # Get recommendations
        recommendations = []
        for idx, (i, sim) in enumerate(zip(indices[0], similarities)):
            if idx >= n_recommendations:
                break
            
            rec = self.beneficiary_data.iloc[i].to_dict()
            rec['similarity_score'] = float(sim)
            recommendations.append(rec)
        
        return recommendations
    
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
                'unemployed': 0.15
            }
        
        scored_beneficiaries = []
        
        # Get income statistics for normalization
        incomes = [b.get('family_annual_income', 0) or 0 for b in beneficiaries]
        max_income = max(incomes) if incomes else 1
        min_income = min(incomes) if incomes else 0
        income_range = max_income - min_income if max_income > min_income else 1
        
        for b in beneficiaries:
            score = 0.0
            
            # Income score - lower income = higher score
            income = float(b.get('family_annual_income', 0) or 0)
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
            
            # Unemployed bonus
            if not b.get('is_currently_employed'):
                score += priority_weights.get('unemployed', 0.15)
            
            b_copy = dict(b)
            b_copy['score'] = round(score, 4)
            scored_beneficiaries.append(b_copy)
        
        # Sort by score descending
        scored_beneficiaries.sort(key=lambda x: x['score'], reverse=True)
        
        return scored_beneficiaries


def get_recommendations(beneficiaries_data, filters=None, max_beneficiaries=50,
                       solo_parent_priority=False, student_priority=False,
                       pwd_priority=False, priority_barangays=None,
                       min_income=0, max_income=999999999):
    """
    Main function to generate beneficiary recommendations.
    
    Args:
        beneficiaries_data: List of beneficiary dictionaries
        filters: Additional filter criteria
        max_beneficiaries: Maximum number of recommendations
        solo_parent_priority: Whether to prioritize solo parents
        student_priority: Whether to prioritize students
        pwd_priority: Whether to prioritize PWDs
        priority_barangays: List of barangays to filter by
        min_income: Minimum income filter
        max_income: Maximum income filter
        
    Returns:
        List of recommended beneficiaries with scores
    """
    if not beneficiaries_data:
        return []
    
    # Apply basic filters
    filtered = []
    for b in beneficiaries_data:
        income = float(b.get('family_annual_income', 0) or 0)
        
        # Income filter
        if income < min_income or income > max_income:
            continue
        
        # Barangay filter - if priority_barangays is provided, filter by them
        if priority_barangays and len(priority_barangays) > 0:
            barangay = b.get('barangay', '')
            if barangay not in priority_barangays:
                continue
        
        filtered.append(b)
    
    if not filtered:
        return []
    
    # Calculate priority weights based on user preferences
    priority_weights = {
        'low_income': 0.3,
        'solo_parent': 0.3 if solo_parent_priority else 0.1,
        'student': 0.2 if student_priority else 0.1,
        'pwd': 0.3 if pwd_priority else 0.1,
        'unemployed': 0.1
    }
    
    # Normalize weights
    total_weight = sum(priority_weights.values())
    priority_weights = {k: v / total_weight for k, v in priority_weights.items()}
    
    # Create recommender and score beneficiaries
    recommender = BeneficiaryRecommender()
    scored = recommender.score_beneficiaries(filtered, priority_weights)
    
    # Return top N beneficiaries
    return scored[:max_beneficiaries]


class ProgramRecommender:
    """
    Content-based program recommender for users.
    
    Recommends programs to users based on:
    - User interaction history (applications) when available
    - User profile (income/status) for cold-start users
    - Program popularity as fallback
    
    Cold-start strategy:
    - Builds a user profile vector from CommunityUsers (income bucket + status flags)
    - Computes cosine similarity between user vector and program TF-IDF vectors
    - Blends similarity, popularity, and status-to-type boosts
    """
    
    # Class-level constants for blending weights
    ALPHA = 0.7  # Weight for profile similarity
    BETA = 0.3   # Weight for popularity
    
    # Status-to-program-type boost values
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
    
    def __init__(self):
        self.vectorizer = None
        self.program_vectors = None
        self.programs = None  # List of program dicts
        self.program_id_to_idx = {}  # Mapping from program id to index
        self.is_fitted = False
    
    def fit(self, programs):
        """
        Fit the recommender model on program data.
        
        Args:
            programs: List of dictionaries with program data, each containing:
                - id: Program ID
                - program_name: Name of the program
                - program_type: Type/category of the program
                - description: Program description
                
        Returns:
            bool: True if fitting was successful, False otherwise
        """
        if not programs or len(programs) < 1:
            return False
        
        self.programs = programs
        
        # Build id->index mapping for boost lookups
        self.program_id_to_idx = {p['id']: idx for idx, p in enumerate(programs)}
        
        # Build text corpus from program name, type, and description
        corpus = []
        for p in programs:
            text_parts = []
            if p.get('program_name'):
                text_parts.append(str(p['program_name']))
            if p.get('program_type'):
                text_parts.append(str(p['program_type']))
            if p.get('description'):
                text_parts.append(str(p['description']))
            corpus.append(' '.join(text_parts))
        
        # Fit TF-IDF vectorizer on program texts
        self.vectorizer = TfidfVectorizer(
            max_features=200,
            stop_words='english',
            ngram_range=(1, 2)
        )
        self.program_vectors = self.vectorizer.fit_transform(corpus)
        self.is_fitted = True
        
        return True
    
    def _income_bucket(self, value):
        """
        Convert income value to bucket token.
        
        Args:
            value: Annual income value (float or None)
            
        Returns:
            str: Income bucket token
        """
        if value is None:
            return "unknown_income"
        try:
            income = float(value)
            if income <= 100000:
                return "low_income"
            elif income <= 300000:
                return "mid_income"
            else:
                return "high_income"
        except (TypeError, ValueError):
            return "unknown_income"
    
    def _build_user_profile_text(self, profile):
        """
        Build profile text string from user profile for TF-IDF vectorization.
        
        Args:
            profile: CommunityUsers model instance or dict with user profile data
            
        Returns:
            str: Text string of tokens representing user profile
        """
        tokens = []
        
        # Income bucket token
        income = getattr(profile, 'family_annual_income', None)
        if income is None and isinstance(profile, dict):
            income = profile.get('family_annual_income')
        tokens.append(self._income_bucket(income))
        
        # Status tokens with related program type keywords
        is_student = getattr(profile, 'is_student', None)
        if is_student is None and isinstance(profile, dict):
            is_student = profile.get('is_student')
        if is_student:
            tokens.extend(['student', 'education'])
        
        is_solo_parent = getattr(profile, 'is_solo_parent', None)
        if is_solo_parent is None and isinstance(profile, dict):
            is_solo_parent = profile.get('is_solo_parent')
        if is_solo_parent:
            tokens.extend(['solo_parent', 'emergency', 'housing'])
        
        # Optional fields - use getattr with defaults
        is_pwd = getattr(profile, 'is_pwd', None)
        if is_pwd is None and isinstance(profile, dict):
            is_pwd = profile.get('is_pwd')
        if is_pwd:
            tokens.extend(['pwd', 'healthcare'])
        
        is_unemployed = getattr(profile, 'is_unemployed', None)
        if is_unemployed is None and isinstance(profile, dict):
            is_unemployed = profile.get('is_unemployed')
        # Also check is_currently_employed as alternative
        if is_unemployed is None:
            is_currently_employed = getattr(profile, 'is_currently_employed', None)
            if is_currently_employed is None and isinstance(profile, dict):
                is_currently_employed = profile.get('is_currently_employed')
            if is_currently_employed is not None:
                is_unemployed = not is_currently_employed
        if is_unemployed:
            tokens.extend(['unemployed', 'employment', 'business', 'emergency'])
        
        is_informal_worker = getattr(profile, 'is_informal_worker', None)
        if is_informal_worker is None and isinstance(profile, dict):
            is_informal_worker = profile.get('is_informal_worker')
        if is_informal_worker:
            tokens.extend(['informal_worker', 'business', 'emergency'])
        
        return ' '.join(tokens)
    
    def _status_type_boost(self, profile, program):
        """
        Calculate status-to-program-type boost.
        
        Args:
            profile: CommunityUsers model instance or dict with user profile data
            program: Program dict with 'program_type' key
            
        Returns:
            float: Boost value to add to score
        """
        boost = 0.0
        program_type = str(program.get('program_type', '')).lower()
        
        # Get profile fields safely
        is_student = getattr(profile, 'is_student', None)
        if is_student is None and isinstance(profile, dict):
            is_student = profile.get('is_student')
            
        is_solo_parent = getattr(profile, 'is_solo_parent', None)
        if is_solo_parent is None and isinstance(profile, dict):
            is_solo_parent = profile.get('is_solo_parent')
            
        is_pwd = getattr(profile, 'is_pwd', None)
        if is_pwd is None and isinstance(profile, dict):
            is_pwd = profile.get('is_pwd')
        
        # Check is_unemployed or derive from is_currently_employed
        is_unemployed = getattr(profile, 'is_unemployed', None)
        if is_unemployed is None and isinstance(profile, dict):
            is_unemployed = profile.get('is_unemployed')
        if is_unemployed is None:
            is_currently_employed = getattr(profile, 'is_currently_employed', None)
            if is_currently_employed is None and isinstance(profile, dict):
                is_currently_employed = profile.get('is_currently_employed')
            if is_currently_employed is not None:
                is_unemployed = not is_currently_employed
                
        is_informal_worker = getattr(profile, 'is_informal_worker', None)
        if is_informal_worker is None and isinstance(profile, dict):
            is_informal_worker = profile.get('is_informal_worker')
        
        income = getattr(profile, 'family_annual_income', None)
        if income is None and isinstance(profile, dict):
            income = profile.get('family_annual_income')
        income_bucket = self._income_bucket(income)
        
        # Apply boosts
        if is_student and 'education' in program_type:
            boost += self.BOOST_STUDENT_EDUCATION
            
        if is_solo_parent:
            if 'emergency' in program_type:
                boost += self.BOOST_SOLO_PARENT_EMERGENCY
            if 'housing' in program_type:
                boost += self.BOOST_SOLO_PARENT_HOUSING
            if 'healthcare' in program_type:
                boost += self.BOOST_SOLO_PARENT_HEALTHCARE
                
        if is_pwd:
            if 'healthcare' in program_type:
                boost += self.BOOST_PWD_HEALTHCARE
            if 'employment' in program_type:
                boost += self.BOOST_PWD_EMPLOYMENT
                
        if is_unemployed:
            if 'employment' in program_type:
                boost += self.BOOST_UNEMPLOYED_EMPLOYMENT
            if 'business' in program_type:
                boost += self.BOOST_UNEMPLOYED_BUSINESS
            if 'emergency' in program_type:
                boost += self.BOOST_UNEMPLOYED_EMERGENCY
                
        if is_informal_worker:
            if 'business' in program_type:
                boost += self.BOOST_INFORMAL_WORKER_BUSINESS
            if 'emergency' in program_type:
                boost += self.BOOST_INFORMAL_WORKER_EMERGENCY
                
        if income_bucket == 'low_income':
            if 'emergency' in program_type:
                boost += self.BOOST_LOW_INCOME_EMERGENCY
            if 'housing' in program_type:
                boost += self.BOOST_LOW_INCOME_HOUSING
        
        return boost
    
    def _normalize(self, scores_dict):
        """
        Normalize scores dictionary to 0..1 range.
        
        Args:
            scores_dict: Dict mapping program_id to score
            
        Returns:
            Dict with normalized scores
        """
        if not scores_dict:
            return {}
        
        values = list(scores_dict.values())
        min_val = min(values)
        max_val = max(values)
        
        if max_val == min_val:
            # All scores are the same, return 0.5 for all
            return {k: 0.5 for k in scores_dict}
        
        return {
            k: (v - min_val) / (max_val - min_val)
            for k, v in scores_dict.items()
        }
    
    def _get_popular_programs(self, interactions=None, top_n=10):
        """
        Get popularity scores for programs.
        
        Uses interaction counts if provided, otherwise uses recency (assumes
        programs list is ordered by recency).
        
        Args:
            interactions: Optional list of interaction dicts with 'program_id'
            top_n: Number of top programs to return
            
        Returns:
            Dict mapping program_id to popularity score (higher = more popular)
        """
        if not self.programs:
            return {}
        
        popularity = {}
        
        if interactions:
            # Count interactions per program
            interaction_counts = {}
            for interaction in interactions:
                pid = interaction.get('program_id')
                if pid is not None:
                    interaction_counts[pid] = interaction_counts.get(pid, 0) + 1
            
            # Use interaction count as popularity
            for p in self.programs:
                popularity[p['id']] = interaction_counts.get(p['id'], 0)
        else:
            # Use index as proxy for recency (lower index = more recent/popular)
            for idx, p in enumerate(self.programs):
                # Invert so first programs have higher scores
                popularity[p['id']] = len(self.programs) - idx
        
        return popularity
    
    def _profile_based_cold_start(self, profile, top_n=10):
        """
        Generate cold-start recommendations based on user profile.
        
        Args:
            profile: CommunityUsers model instance or dict with profile data
            top_n: Number of recommendations to return
            
        Returns:
            List of recommended program dicts with 'score' key
        """
        if not self.is_fitted or profile is None:
            return self._popularity_fallback(top_n)
        
        # Build user profile text
        user_text = self._build_user_profile_text(profile)
        
        if not user_text.strip():
            return self._popularity_fallback(top_n)
        
        try:
            # Vectorize user profile text
            user_vector = self.vectorizer.transform([user_text])
            
            # Compute cosine similarity with all programs
            similarities = cosine_similarity(user_vector, self.program_vectors)[0]
            
            # Build similarity scores dict
            similarity_scores = {
                self.programs[idx]['id']: float(sim)
                for idx, sim in enumerate(similarities)
            }
        except Exception:
            # If vectorization fails, fallback to popularity
            return self._popularity_fallback(top_n)
        
        # Get popularity scores
        popularity_scores = self._get_popular_programs()
        
        # Normalize both score sets
        norm_similarity = self._normalize(similarity_scores)
        norm_popularity = self._normalize(popularity_scores)
        
        # Compute final scores with blending and boosts
        final_scores = {}
        for p in self.programs:
            pid = p['id']
            sim_score = norm_similarity.get(pid, 0)
            pop_score = norm_popularity.get(pid, 0)
            boost = self._status_type_boost(profile, p)
            
            final_scores[pid] = (
                self.ALPHA * sim_score +
                self.BETA * pop_score +
                boost
            )
        
        # Sort by score and return top N
        sorted_programs = sorted(
            final_scores.items(),
            key=lambda x: x[1],
            reverse=True
        )[:top_n]
        
        # Build result list
        results = []
        for pid, score in sorted_programs:
            idx = self.program_id_to_idx.get(pid)
            if idx is not None:
                program_copy = dict(self.programs[idx])
                program_copy['score'] = round(score, 4)
                results.append(program_copy)
        
        return results
    
    def _popularity_fallback(self, top_n=10):
        """
        Return programs ranked by popularity only (fallback for missing profile).
        
        Args:
            top_n: Number of recommendations to return
            
        Returns:
            List of program dicts with 'score' key
        """
        if not self.programs:
            return []
        
        popularity = self._get_popular_programs()
        norm_popularity = self._normalize(popularity)
        
        sorted_programs = sorted(
            norm_popularity.items(),
            key=lambda x: x[1],
            reverse=True
        )[:top_n]
        
        results = []
        for pid, score in sorted_programs:
            idx = self.program_id_to_idx.get(pid)
            if idx is not None:
                program_copy = dict(self.programs[idx])
                program_copy['score'] = round(score, 4)
                results.append(program_copy)
        
        return results
    
    def recommend_for_user(self, user_id, top_n=10, interactions=None, profile=None,
                          get_profile_func=None, get_interactions_func=None):
        """
        Generate program recommendations for a user.
        
        Args:
            user_id: User ID to generate recommendations for
            top_n: Number of recommendations to return
            interactions: Optional pre-fetched list of user interactions (applications)
            profile: Optional pre-fetched CommunityUsers profile
            get_profile_func: Optional callback to fetch profile: func(user_id) -> profile
            get_interactions_func: Optional callback to fetch interactions: func(user_id) -> list
            
        Returns:
            List of recommended program dicts with 'score' key
        """
        if not self.is_fitted:
            return []
        
        # Try to get interactions
        user_interactions = interactions
        if user_interactions is None and get_interactions_func is not None:
            try:
                user_interactions = get_interactions_func(user_id)
            except Exception:
                user_interactions = None
        
        # If user has interactions, use interaction-weighted logic (existing behavior)
        if user_interactions and len(user_interactions) > 0:
            return self._interaction_based_recommendations(
                user_interactions, top_n
            )
        
        # Cold start path: try profile-based recommendations
        user_profile = profile
        if user_profile is None and get_profile_func is not None:
            try:
                user_profile = get_profile_func(user_id)
            except Exception:
                user_profile = None
        
        if user_profile is not None:
            return self._profile_based_cold_start(user_profile, top_n)
        
        # Ultimate fallback: popularity only
        return self._popularity_fallback(top_n)
    
    def _interaction_based_recommendations(self, interactions, top_n=10):
        """
        Generate recommendations based on user's interaction history.
        
        This is the existing logic for users with interactions.
        Uses program similarity to previously interacted programs.
        
        Args:
            interactions: List of interaction dicts with 'program_id'
            top_n: Number of recommendations to return
            
        Returns:
            List of recommended program dicts with 'score' key
        """
        if not self.is_fitted or not interactions:
            return self._popularity_fallback(top_n)
        
        # Get programs the user has interacted with
        interacted_ids = set()
        for interaction in interactions:
            pid = interaction.get('program_id')
            if pid is not None:
                interacted_ids.add(pid)
        
        if not interacted_ids:
            return self._popularity_fallback(top_n)
        
        # Build aggregate vector from interacted programs
        interacted_vectors = []
        for pid in interacted_ids:
            idx = self.program_id_to_idx.get(pid)
            if idx is not None:
                interacted_vectors.append(self.program_vectors[idx].toarray())
        
        if not interacted_vectors:
            return self._popularity_fallback(top_n)
        
        # Average the vectors
        avg_vector = np.mean(interacted_vectors, axis=0)
        
        # Compute similarity to all programs
        similarities = cosine_similarity(avg_vector, self.program_vectors)[0]
        
        # Build scores, excluding already interacted programs
        scores = {}
        for idx, sim in enumerate(similarities):
            pid = self.programs[idx]['id']
            if pid not in interacted_ids:
                scores[pid] = float(sim)
        
        # Sort and return top N
        sorted_programs = sorted(
            scores.items(),
            key=lambda x: x[1],
            reverse=True
        )[:top_n]
        
        results = []
        for pid, score in sorted_programs:
            idx = self.program_id_to_idx.get(pid)
            if idx is not None:
                program_copy = dict(self.programs[idx])
                program_copy['score'] = round(score, 4)
                results.append(program_copy)
        
        return results