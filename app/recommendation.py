"""
Recommendation System for Financial Programs

This module implements a Content-Based Filtering recommendation algorithm using TF-IDF
(Term Frequency-Inverse Document Frequency) to recommend financial assistance programs to users.

Algorithm Choice: Content-Based Filtering with TF-IDF
Rationale:
1. No Historical Data - Collaborative filtering requires extensive user-item interaction history
2. Rich Metadata - Programs have descriptive attributes (type, period, description)
3. Cold Start Problem - Works for new users and new programs without prior interactions
4. Interpretability - Can explain why programs are recommended based on similarity
5. Scalability - Efficient for small to medium-sized datasets
6. Context-Aware - Can incorporate user preferences and interaction history

The algorithm:
1. Creates feature vectors from program attributes (name, type, period, description)
2. Uses TF-IDF to weight terms based on their importance
3. Calculates cosine similarity between programs
4. Recommends programs similar to user's interaction history
"""

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import pandas as pd
from typing import List, Dict, Any, Optional
from .models import Programs, UserProgramInteraction, User
from sqlalchemy import func


class ProgramRecommender:
    """Content-based recommendation system for financial programs"""
    
    def __init__(self):
        self.vectorizer = TfidfVectorizer(
            max_features=100,
            stop_words='english',
            ngram_range=(1, 2),  # Use unigrams and bigrams
            min_df=1
        )
        self.program_features = None
        self.program_ids = None
        self.similarity_matrix = None
    
    def _create_program_features(self, program: Programs) -> str:
        """
        Create a text representation of program for feature extraction.
        Combines all relevant program attributes into a single string.
        """
        features = []
        
        if program.program_name:
            features.append(program.program_name)
        
        if program.program_type:
            # Repeat type to increase its weight in recommendations
            features.append(f"{program.program_type} {program.program_type}")
        
        if program.program_period:
            features.append(program.program_period)
        
        if program.description:
            features.append(program.description)
        
        return ' '.join(features)
    
    def fit(self, programs: List[Programs]):
        """
        Fit the recommendation model on available programs.
        
        Args:
            programs: List of Programs objects to build recommendation model
        """
        if not programs:
            return
        
        # Create feature strings for all programs
        program_texts = [self._create_program_features(p) for p in programs]
        self.program_ids = [p.id for p in programs]
        
        # Create TF-IDF matrix
        self.program_features = self.vectorizer.fit_transform(program_texts)
        
        # Calculate similarity matrix (program to program similarities)
        self.similarity_matrix = cosine_similarity(self.program_features)
    
    def get_similar_programs(self, program_id: int, top_n: int = 5) -> List[int]:
        """
        Get programs similar to a given program.
        
        Args:
            program_id: ID of the program to find similar programs for
            top_n: Number of similar programs to return
            
        Returns:
            List of program IDs sorted by similarity (most similar first)
        """
        if self.similarity_matrix is None or program_id not in self.program_ids:
            return []
        
        # Get index of the program
        program_idx = self.program_ids.index(program_id)
        
        # Get similarity scores
        similarity_scores = list(enumerate(self.similarity_matrix[program_idx]))
        
        # Sort by similarity (excluding the program itself)
        similarity_scores = sorted(similarity_scores, key=lambda x: x[1], reverse=True)
        similarity_scores = [s for s in similarity_scores if s[0] != program_idx]
        
        # Get top N similar programs
        top_similar = similarity_scores[:top_n]
        
        return [self.program_ids[idx] for idx, _ in top_similar]
    
    def recommend_for_user(self, user_id: int, top_n: int = 5, 
                          exclude_interacted: bool = True) -> List[Dict[str, Any]]:
        """
        Recommend programs for a user based on their interaction history.
        
        Args:
            user_id: ID of the user to recommend programs for
            top_n: Number of programs to recommend
            exclude_interacted: Whether to exclude programs user has already interacted with
            
        Returns:
            List of dictionaries containing program_id and recommendation_score
        """
        # Get user's interaction history
        interactions = UserProgramInteraction.query.filter_by(user_id=user_id).all()
        
        if not interactions:
            # For new users, recommend popular programs
            return self._get_popular_programs(top_n)
        
        # Get programs user has interacted with
        interacted_program_ids = [i.program_id for i in interactions]
        
        # Weight interactions by type
        interaction_weights = {
            'apply': 3.0,    # Applications indicate strong interest
            'bookmark': 2.0, # Bookmarks indicate moderate interest
            'view': 1.0      # Views indicate basic interest
        }
        
        # Aggregate scores for all programs
        program_scores = {}
        
        for interaction in interactions:
            weight = interaction_weights.get(interaction.interaction_type, 1.0)
            similar_programs = self.get_similar_programs(interaction.program_id, top_n=10)
            
            for similar_program_id in similar_programs:
                if similar_program_id not in program_scores:
                    program_scores[similar_program_id] = 0
                program_scores[similar_program_id] += weight
        
        # Exclude already interacted programs if requested
        if exclude_interacted:
            for program_id in interacted_program_ids:
                program_scores.pop(program_id, None)
        
        # Sort and get top N
        sorted_programs = sorted(program_scores.items(), key=lambda x: x[1], reverse=True)
        top_programs = sorted_programs[:top_n]
        
        return [
            {'program_id': program_id, 'recommendation_score': score}
            for program_id, score in top_programs
        ]
    
    def _get_popular_programs(self, top_n: int = 5) -> List[Dict[str, Any]]:
        """
        Get most popular programs based on interaction count.
        Used for cold start (new users without interaction history).
        
        Args:
            top_n: Number of programs to return
            
        Returns:
            List of dictionaries containing program_id and interaction_count
        """
        from . import db
        
        popular = db.session.query(
            UserProgramInteraction.program_id,
            func.count(UserProgramInteraction.id).label('interaction_count')
        ).group_by(
            UserProgramInteraction.program_id
        ).order_by(
            func.count(UserProgramInteraction.id).desc()
        ).limit(top_n).all()
        
        if not popular:
            # If no interactions yet, return most recent programs
            recent_programs = Programs.query.order_by(Programs.date.desc()).limit(top_n).all()
            return [
                {'program_id': p.id, 'recommendation_score': 1.0}
                for p in recent_programs
            ]
        
        return [
            {'program_id': program_id, 'recommendation_score': float(count)}
            for program_id, count in popular
        ]


def get_recommender() -> ProgramRecommender:
    """
    Factory function to create and fit a recommender instance.
    
    Returns:
        Fitted ProgramRecommender instance
    """
    recommender = ProgramRecommender()
    programs = Programs.query.all()
    recommender.fit(programs)
    return recommender


def recommend_programs_for_user(user_id: int, top_n: int = 5) -> List[Programs]:
    """
    High-level function to get program recommendations for a user.
    
    Args:
        user_id: ID of the user
        top_n: Number of programs to recommend
        
    Returns:
        List of Programs objects recommended for the user
    """
    recommender = get_recommender()
    recommendations = recommender.recommend_for_user(user_id, top_n)
    
    if not recommendations:
        return []
    
    # Fetch actual program objects
    program_ids = [r['program_id'] for r in recommendations]
    programs = Programs.query.filter(Programs.id.in_(program_ids)).all()
    
    # Sort by recommendation order
    program_dict = {p.id: p for p in programs}
    return [program_dict[pid] for pid in program_ids if pid in program_dict]
