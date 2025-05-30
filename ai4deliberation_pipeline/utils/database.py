#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Database Utilities

Common database operations and statistics for the AI4Deliberation pipeline.
"""

import sqlite3
import logging
from typing import Dict, Any, Optional
from contextlib import contextmanager


@contextmanager
def create_database_connection(database_path: str):
    """
    Create a database connection context manager.
    
    Args:
        database_path: Path to SQLite database file
        
    Yields:
        sqlite3.Connection: Database connection
    """
    conn = None
    try:
        conn = sqlite3.connect(database_path)
        conn.row_factory = sqlite3.Row  # Enable column access by name
        yield conn
    except Exception as e:
        if conn:
            conn.rollback()
        raise e
    finally:
        if conn:
            conn.close()


def get_database_stats(database_path: str) -> Dict[str, Any]:
    """
    Get comprehensive database statistics.
    
    Args:
        database_path: Path to SQLite database file
        
    Returns:
        dict: Database statistics
    """
    stats = {}
    
    try:
        with create_database_connection(database_path) as conn:
            cursor = conn.cursor()
            
            # Consultation statistics
            cursor.execute("SELECT COUNT(*) FROM consultations")
            stats['total_consultations'] = cursor.fetchone()[0]
            
            # Article statistics
            cursor.execute("SELECT COUNT(*) FROM articles")
            stats['total_articles'] = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM articles WHERE content_cleaned IS NOT NULL")
            stats['articles_processed'] = cursor.fetchone()[0]
            
            # Document statistics
            cursor.execute("SELECT COUNT(*) FROM documents")
            stats['total_documents'] = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM documents WHERE content IS NOT NULL")
            stats['documents_with_content'] = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM documents WHERE content_cleaned IS NOT NULL")
            stats['documents_cleaned'] = cursor.fetchone()[0]
            
            # Quality statistics
            cursor.execute("""
                SELECT AVG(CAST(badness_score AS REAL)), MIN(CAST(badness_score AS REAL)), MAX(CAST(badness_score AS REAL))
                FROM documents WHERE badness_score IS NOT NULL AND typeof(badness_score) IN ('integer', 'real')
            """)
            row = cursor.fetchone()
            if row:
                if isinstance(row[0], (int, float)):
                    stats['avg_badness_score'] = round(row[0], 3)
                if isinstance(row[1], (int, float)):
                    stats['min_badness_score'] = round(row[1], 3)
                if isinstance(row[2], (int, float)):
                    stats['max_badness_score'] = round(row[2], 3)
            
            # Language statistics
            cursor.execute("""
                SELECT AVG(greek_percentage), AVG(english_percentage)
                FROM documents WHERE greek_percentage IS NOT NULL
            """)
            row = cursor.fetchone()
            if row and row[0] is not None:
                stats['avg_greek_percentage'] = round(row[0], 1)
                stats['avg_english_percentage'] = round(row[1], 1)
            
            # Comment statistics
            cursor.execute("SELECT COUNT(*) FROM comments")
            stats['total_comments'] = cursor.fetchone()[0]
            
    except Exception as e:
        logging.error(f"Error getting database stats: {e}")
        stats['error'] = str(e)
    
    return stats


def execute_query(database_path: str, query: str, params: tuple = ()) -> list:
    """
    Execute a database query and return results.
    
    Args:
        database_path: Path to SQLite database file
        query: SQL query to execute
        params: Query parameters
        
    Returns:
        list: Query results
    """
    try:
        with create_database_connection(database_path) as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return cursor.fetchall()
    except Exception as e:
        logging.error(f"Error executing query: {e}")
        raise


def execute_update(database_path: str, query: str, params: tuple = ()) -> int:
    """
    Execute a database update and return rows affected.
    
    Args:
        database_path: Path to SQLite database file
        query: SQL update query
        params: Query parameters
        
    Returns:
        int: Number of rows affected
    """
    try:
        with create_database_connection(database_path) as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            conn.commit()
            return cursor.rowcount
    except Exception as e:
        logging.error(f"Error executing update: {e}")
        raise 