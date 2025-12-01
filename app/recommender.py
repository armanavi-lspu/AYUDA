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
        """
        df = self._prepare_dataframe(beneficiaries)
        if df is None or len(df) < 2:
            return False
        
        self.beneficiary_data = df
        
        # Create and fit preprocessor
        self.preprocessor = self._create_preprocessor(df)
        
        # Transform features
        features = self.preprocessor.fit_transform(df)
        
        # Fit NearestNeighbors model
        n_neighbors = min(len(df), 50)  # Use at most 50 neighbors
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
