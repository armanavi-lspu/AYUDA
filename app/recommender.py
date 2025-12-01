"""
Content-Based Beneficiary Recommendation System

This module implements a content-based filtering algorithm using scikit-learn
to recommend beneficiaries for programs based on their profile attributes.

The approach uses:
- TfidfVectorizer for text features (occupation, barangay)
- ColumnTransformer for combining text and numeric features
- NearestNeighbors for finding similar beneficiaries
"""

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import StandardScaler
from sklearn.neighbors import NearestNeighbors
import joblib
import os
from typing import List, Dict, Optional, Any


class BeneficiaryRecommender:
    """
    Content-based recommendation system for beneficiaries.
    
    Uses a combination of text features (TF-IDF) and categorical/numeric features
    to find the most suitable beneficiaries for a program based on their profiles.
    """
    
    def __init__(self, n_neighbors: int = 50):
        """
        Initialize the recommender.
        
        Args:
            n_neighbors: Maximum number of neighbors to return
        """
        self.n_neighbors = n_neighbors
        self.model = None
        self.preprocessor = None
        self.feature_names = None
        self.beneficiary_ids = None
        
    def _create_preprocessor(self, df: pd.DataFrame) -> ColumnTransformer:
        """
        Create a ColumnTransformer for preprocessing features.
        
        Handles text features with TF-IDF and numeric features with StandardScaler.
        """
        # Define text columns that will use TF-IDF
        text_columns = []
        if 'barangay' in df.columns:
            text_columns.append('barangay')
        if 'occupation' in df.columns:
            text_columns.append('occupation')
        if 'municipality' in df.columns:
            text_columns.append('municipality')
        if 'sitio' in df.columns:
            text_columns.append('sitio')
            
        # Define numeric columns
        numeric_columns = []
        if 'family_annual_income' in df.columns:
            numeric_columns.append('family_annual_income')
        if 'age' in df.columns:
            numeric_columns.append('age')
            
        # Define boolean columns (will be treated as numeric 0/1)
        bool_columns = []
        if 'is_solo_parent' in df.columns:
            bool_columns.append('is_solo_parent')
        if 'is_student' in df.columns:
            bool_columns.append('is_student')
        if 'is_pwd' in df.columns:
            bool_columns.append('is_pwd')
        if 'is_currently_employed' in df.columns:
            bool_columns.append('is_currently_employed')
            
        transformers = []
        
        # Add TF-IDF transformers for each text column
        for col in text_columns:
            transformers.append((
                f'tfidf_{col}',
                TfidfVectorizer(max_features=50, lowercase=True, ngram_range=(1, 2)),
                col
            ))
            
        # Add StandardScaler for numeric columns
        if numeric_columns:
            transformers.append((
                'numeric',
                StandardScaler(),
                numeric_columns
            ))
            
        # Add passthrough for boolean columns (already 0/1)
        if bool_columns:
            transformers.append((
                'boolean',
                'passthrough',
                bool_columns
            ))
            
        return ColumnTransformer(
            transformers=transformers,
            remainder='drop'
        )
    
    def _prepare_dataframe(self, beneficiaries: List[Dict[str, Any]]) -> pd.DataFrame:
        """
        Convert list of beneficiary dictionaries to a pandas DataFrame.
        
        Args:
            beneficiaries: List of dictionaries with beneficiary data
            
        Returns:
            DataFrame with beneficiary features
        """
        df = pd.DataFrame(beneficiaries)
        
        # Fill missing text values with empty strings
        text_cols = ['barangay', 'occupation', 'municipality', 'sitio']
        for col in text_cols:
            if col in df.columns:
                df[col] = df[col].fillna('').astype(str)
                
        # Fill missing numeric values with median or 0
        numeric_cols = ['family_annual_income', 'age']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
                
        # Fill missing boolean values with False
        bool_cols = ['is_solo_parent', 'is_student', 'is_pwd', 'is_currently_employed']
        for col in bool_cols:
            if col in df.columns:
                df[col] = df[col].fillna(False).astype(int)
                
        return df
    
    def fit(self, beneficiaries: List[Dict[str, Any]]) -> 'BeneficiaryRecommender':
        """
        Fit the recommender model on beneficiary data.
        
        Args:
            beneficiaries: List of dictionaries containing beneficiary profiles
            
        Returns:
            self
        """
        if not beneficiaries:
            return self
            
        df = self._prepare_dataframe(beneficiaries)
        self.beneficiary_ids = df['user_id'].values if 'user_id' in df.columns else None
        
        # Create and fit the preprocessor
        self.preprocessor = self._create_preprocessor(df)
        
        # Transform the data
        X = self.preprocessor.fit_transform(df)
        
        # Handle sparse matrices from TF-IDF
        if hasattr(X, 'toarray'):
            X = X.toarray()
            
        # Fit the NearestNeighbors model
        self.model = NearestNeighbors(
            n_neighbors=min(self.n_neighbors, len(beneficiaries)),
            algorithm='auto',
            metric='cosine'
        )
        self.model.fit(X)
        
        return self
    
    def recommend(
        self,
        beneficiaries: List[Dict[str, Any]],
        target_profile: Optional[Dict[str, Any]] = None,
        filters: Optional[Dict[str, Any]] = None,
        max_results: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Generate recommendations for beneficiaries.
        
        Uses content-based filtering to score and rank beneficiaries based on
        their profile similarity and priority criteria.
        
        Args:
            beneficiaries: List of beneficiary profiles
            target_profile: Optional target profile to find similar beneficiaries
            filters: Optional filters for prioritization
            max_results: Maximum number of results to return
            
        Returns:
            List of recommended beneficiaries with scores
        """
        if not beneficiaries:
            return []
            
        df = self._prepare_dataframe(beneficiaries)
        
        # Apply filters first
        filtered_df = self._apply_filters(df, filters)
        
        if filtered_df.empty:
            return []
            
        # Calculate scores using content-based approach
        scored_df = self._calculate_scores(filtered_df, target_profile, filters)
        
        # Sort by score (descending) and limit results
        scored_df = scored_df.sort_values('score', ascending=False).head(max_results)
        
        # Convert to list of dictionaries
        results = []
        for _, row in scored_df.iterrows():
            result = {
                'user_id': int(row['user_id']) if 'user_id' in row else None,
                'name': f"{row.get('first_name', '')} {row.get('last_name', '')}".strip(),
                'email': row.get('email', ''),
                'barangay': row.get('barangay', ''),
                'income': float(row.get('family_annual_income', 0)),
                'is_solo_parent': bool(row.get('is_solo_parent', False)),
                'is_student': bool(row.get('is_student', False)),
                'is_pwd': bool(row.get('is_pwd', False)),
                'age': int(row.get('age', 0)) if row.get('age') else 0,
                'score': float(row.get('score', 0))
            }
            results.append(result)
            
        return results
    
    def _apply_filters(
        self,
        df: pd.DataFrame,
        filters: Optional[Dict[str, Any]]
    ) -> pd.DataFrame:
        """
        Apply filtering criteria to the beneficiary DataFrame.
        
        Args:
            df: DataFrame with beneficiary data
            filters: Dictionary of filter criteria
            
        Returns:
            Filtered DataFrame
        """
        if not filters:
            return df
            
        filtered = df.copy()
        
        # Filter by barangay
        if filters.get('priority_barangay'):
            filtered = filtered[filtered['barangay'] == filters['priority_barangay']]
            
        # Filter by income range
        min_income = filters.get('min_income', 0)
        max_income = filters.get('max_income', float('inf'))
        if 'family_annual_income' in filtered.columns:
            filtered = filtered[
                (filtered['family_annual_income'] >= min_income) &
                (filtered['family_annual_income'] <= max_income)
            ]
            
        return filtered
    
    def _calculate_scores(
        self,
        df: pd.DataFrame,
        target_profile: Optional[Dict[str, Any]],
        filters: Optional[Dict[str, Any]]
    ) -> pd.DataFrame:
        """
        Calculate recommendation scores for beneficiaries.
        
        The score is computed based on:
        1. Content similarity (if target profile provided)
        2. Priority bonuses (solo parent, student, etc.)
        3. Need-based scoring (lower income = higher priority)
        
        Args:
            df: Filtered DataFrame with beneficiary data
            target_profile: Optional target profile for similarity matching
            filters: Priority filters
            
        Returns:
            DataFrame with added 'score' column
        """
        scored_df = df.copy()
        
        # Initialize base score
        scored_df['score'] = 0.0
        
        # 1. Content similarity scoring (if we have a target profile)
        if target_profile and self.model is not None and self.preprocessor is not None:
            try:
                # Transform the current data
                X = self.preprocessor.transform(scored_df)
                if hasattr(X, 'toarray'):
                    X = X.toarray()
                
                # Use kneighbors to get similarity-based ranking
                distances, indices = self.model.kneighbors(X)
                
                # Convert distances to similarity scores (1 - distance for cosine)
                # Average distance gives us an indication of how central each point is
                avg_distances = distances.mean(axis=1)
                max_dist = avg_distances.max() if avg_distances.max() > 0 else 1
                similarity_scores = 1 - (avg_distances / max_dist)
                scored_df['score'] += similarity_scores * 30  # Weight for content similarity
            except Exception:
                # If content-based scoring fails, continue with priority-based
                pass
        
        # 2. Need-based scoring (lower income = higher score)
        if 'family_annual_income' in scored_df.columns:
            max_income = scored_df['family_annual_income'].max()
            if max_income > 0:
                # Normalize income inversely (0 income = 1.0 score, max income = 0.0)
                income_score = 1 - (scored_df['family_annual_income'] / max_income)
                scored_df['score'] += income_score * 40  # Highest weight for need
        
        # 3. Priority bonuses based on filters
        if filters:
            # Solo parent priority
            if filters.get('solo_parent_priority') and 'is_solo_parent' in scored_df.columns:
                scored_df.loc[scored_df['is_solo_parent'] == 1, 'score'] += 15
                
            # Student priority
            if filters.get('student_priority') and 'is_student' in scored_df.columns:
                scored_df.loc[scored_df['is_student'] == 1, 'score'] += 15
                
            # PWD priority (always give some bonus to PWD)
            if 'is_pwd' in scored_df.columns:
                scored_df.loc[scored_df['is_pwd'] == 1, 'score'] += 10
                
        # 4. Unemployed priority
        if 'is_currently_employed' in scored_df.columns:
            scored_df.loc[scored_df['is_currently_employed'] == 0, 'score'] += 5
            
        # Normalize final score to 0-100 range
        max_score = scored_df['score'].max()
        if max_score > 0:
            scored_df['score'] = (scored_df['score'] / max_score) * 100
            
        return scored_df
    
    def save_model(self, filepath: str) -> None:
        """
        Save the trained model to disk.
        
        Args:
            filepath: Path to save the model
        """
        model_data = {
            'model': self.model,
            'preprocessor': self.preprocessor,
            'beneficiary_ids': self.beneficiary_ids,
            'n_neighbors': self.n_neighbors
        }
        os.makedirs(os.path.dirname(filepath), exist_ok=True) if os.path.dirname(filepath) else None
        joblib.dump(model_data, filepath)
        
    def load_model(self, filepath: str) -> 'BeneficiaryRecommender':
        """
        Load a trained model from disk.
        
        Args:
            filepath: Path to the saved model
            
        Returns:
            self
        """
        if os.path.exists(filepath):
            model_data = joblib.load(filepath)
            self.model = model_data.get('model')
            self.preprocessor = model_data.get('preprocessor')
            self.beneficiary_ids = model_data.get('beneficiary_ids')
            self.n_neighbors = model_data.get('n_neighbors', 50)
        return self


def generate_beneficiary_recommendations(
    beneficiaries: List[Dict[str, Any]],
    filters: Optional[Dict[str, Any]] = None,
    max_results: int = 50
) -> List[Dict[str, Any]]:
    """
    Generate beneficiary recommendations using content-based filtering.
    
    This is the main entry point for the recommendation system.
    
    Args:
        beneficiaries: List of beneficiary profiles (dictionaries)
        filters: Optional filtering and priority criteria
        max_results: Maximum number of recommendations to return
        
    Returns:
        List of recommended beneficiaries with scores
    """
    recommender = BeneficiaryRecommender(n_neighbors=max_results)
    
    # Fit the model on all beneficiaries
    if beneficiaries:
        recommender.fit(beneficiaries)
    
    # Generate recommendations
    recommendations = recommender.recommend(
        beneficiaries=beneficiaries,
        filters=filters,
        max_results=max_results
    )
    
    return recommendations
