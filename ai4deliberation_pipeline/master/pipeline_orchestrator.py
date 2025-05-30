#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pipeline Orchestrator

Main integration module that orchestrates the complete AI4Deliberation pipeline
with efficient data flow: scrape → extract → clean → store once.
"""

import os
import sys
import time
import logging
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass

# Add paths for existing modules
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
sys.path.extend([
    project_root,
    os.path.join(project_root, 'ai4deliberation_pipeline'),
])

# Import configuration and utilities
from config.config_manager import load_config
from utils.logging_utils import setup_logging
from utils.data_flow import ContentProcessor, ProcessedContent
from utils.database import create_database_connection

# Import unified modules
from scraper.scrape_single_consultation import scrape_and_store
from scraper.db_models import init_db

# For now, we'll disable the discovery functionality to get the basic pipeline working
# from ..scraper.scrape_to_db import discover_new_consultations


@dataclass
class PipelineResult:
    """Result of pipeline processing."""
    success: bool
    consultation_id: Optional[int]
    articles_processed: int
    documents_processed: int
    processing_time: float
    errors: List[str]


class PipelineOrchestrator:
    """
    Main pipeline orchestrator that coordinates all processing modules.
    
    Implements efficient pipeline: scrape → extract → clean → store once
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize pipeline orchestrator.
        
        Args:
            config: Optional configuration dictionary
        """
        self.config = config or load_config()
        self.logger = setup_logging(self.config, "pipeline_orchestrator")
        
        # Initialize content processor
        self.content_processor = ContentProcessor(self.config)
        
        # Database path
        self.database_path = self.config['database']['default_path']
        
        self.logger.info("Pipeline orchestrator initialized")
    
    def process_consultation(self, consultation_url: str, force_reprocess: bool = False) -> PipelineResult:
        """
        Process a single consultation through the complete pipeline.
        
        Args:
            consultation_url: URL of consultation to process
            force_reprocess: Whether to reprocess existing content
            
        Returns:
            PipelineResult: Processing results
        """
        start_time = time.time()
        errors = []
        consultation_id = None
        articles_processed = 0
        documents_processed = 0
        
        try:
            self.logger.info(f"Starting pipeline processing for: {consultation_url}")
            
            # Step 1: Scrape consultation data
            self.logger.info("Step 1: Scraping consultation data...")
            consultation_id = self._scrape_consultation(consultation_url)
            if consultation_id is None:
                errors.append("Failed to scrape consultation data")
                return PipelineResult(False, None, 0, 0, time.time() - start_time, errors)
            
            self.logger.info(f"Scraped consultation ID: {consultation_id}")
            
            # Step 2: Process articles with integrated pipeline
            self.logger.info("Step 2: Processing articles...")
            articles_processed = self._process_consultation_articles(consultation_id, force_reprocess)
            
            # Step 3: Process documents with integrated pipeline  
            self.logger.info("Step 3: Processing documents...")
            documents_processed = self._process_consultation_documents(consultation_id, force_reprocess)
            
            processing_time = time.time() - start_time
            self.logger.info(f"Pipeline completed: {articles_processed} articles, {documents_processed} documents in {processing_time:.2f}s")
            
            return PipelineResult(
                success=True,
                consultation_id=consultation_id,
                articles_processed=articles_processed,
                documents_processed=documents_processed,
                processing_time=processing_time,
                errors=errors
            )
            
        except Exception as e:
            self.logger.error(f"Pipeline processing failed: {e}")
            errors.append(str(e))
            return PipelineResult(
                success=False,
                consultation_id=consultation_id,
                articles_processed=articles_processed,
                documents_processed=documents_processed,
                processing_time=time.time() - start_time,
                errors=errors
            )
    
    def _scrape_consultation(self, url: str) -> Optional[int]:
        """
        Scrape consultation data from URL.
        
        Args:
            url: URL to scrape
            
        Returns:
            int: Consultation ID if successful, None otherwise
        """
        try:
            self.logger.info("Step 1: Checking if consultation already exists...")
            
            # Initialize database connection for scraper
            engine, Session = init_db(f'sqlite:///{self.database_path}')
            session = Session()
            
            try:
                # First check if consultation already exists
                from scraper.db_models import Consultation
                
                # Normalize URLs for comparison
                normalized_url = url.replace('http://', '').replace('https://', '')
                
                existing_consultation = session.query(Consultation).filter(
                    Consultation.url.like(f'%{normalized_url.split("?")[0]}%')
                ).first()
                
                if existing_consultation:
                    consultation_id = existing_consultation.id
                    self.logger.info(f"Consultation already exists with ID: {consultation_id}")
                    return consultation_id
                
                # If consultation doesn't exist, run scraper
                self.logger.info("Consultation not found, running scraper...")
                result = scrape_and_store(url, session)
                
                if result:
                    self.logger.info("Scraping successful")
                    
                    # Find the consultation ID by URL
                    consultation = session.query(Consultation).filter(
                        Consultation.url.like(f'%{normalized_url.split("?")[0]}%')
                    ).first()
                    
                    if consultation:
                        consultation_id = consultation.id
                        self.logger.info(f"New consultation created with ID: {consultation_id}")
                        
                        # Commit the session to ensure data is saved
                        session.commit()
                        return consultation_id
                    else:
                        self.logger.error("Could not find consultation in database after scraping")
                        return None
                        
                else:
                    self.logger.error("Scraping failed")
                    return None
                    
            finally:
                session.close()
                
        except Exception as e:
            self.logger.error(f"Error scraping consultation: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _process_consultation_articles(self, consultation_id: int, force_reprocess: bool = False) -> int:
        """
        Process articles for a consultation with integrated pipeline.
        
        Args:
            consultation_id: ID of consultation to process
            force_reprocess: Whether to reprocess existing content
            
        Returns:
            int: Number of articles processed
        """
        try:
            with create_database_connection(self.database_path) as conn:
                cursor = conn.cursor()
                
                # Get articles that need processing
                if force_reprocess:
                    query = "SELECT id, raw_html FROM articles WHERE consultation_id = ? AND raw_html IS NOT NULL"
                else:
                    # Process if raw_html exists AND (content_cleaned is NULL OR content is NULL)
                    # This ensures we re-process if markdownification failed or if rust cleaning failed.
                    query = """
                        SELECT id, raw_html FROM articles 
                        WHERE consultation_id = ? AND raw_html IS NOT NULL 
                        AND (content_cleaned IS NULL OR content IS NULL)
                    """
                
                cursor.execute(query, (consultation_id,))
                articles = cursor.fetchall()
                
                if not articles:
                    self.logger.info("No articles need processing")
                    return 0
                
                self.logger.info(f"Processing {len(articles)} articles")
                processed_count = 0
                
                for article_id, html_content in articles:
                    try:
                        if not html_content: # Skip if raw_html is somehow empty despite query
                            self.logger.warning(f"Skipping article {article_id} due to empty raw_html_content.")
                            continue

                        # Process through integrated pipeline (html_content is raw_html)
                        result = self.content_processor.process_content_pipeline(html_content, "html")
                        
                        # Update database with results (single write)
                        # articles.content gets markdownified HTML (result.original_content)
                        # articles.content_cleaned gets Rust-cleaned markdown (result.cleaned_content)
                        cursor.execute("""
                            UPDATE articles 
                            SET content = ?, content_cleaned = ?, extraction_method = ?
                            WHERE id = ?
                        """, (result.original_content, result.cleaned_content, result.extraction_method, article_id))
                        
                        processed_count += 1
                        
                        if processed_count % 10 == 0:
                            conn.commit()
                            self.logger.info(f"Processed {processed_count}/{len(articles)} articles")
                    
                    except Exception as e:
                        self.logger.error(f"Error processing article {article_id}: {e}")
                
                conn.commit()
                self.logger.info(f"Completed processing {processed_count} articles")
                return processed_count
                
        except Exception as e:
            self.logger.error(f"Error processing consultation articles: {e}")
            return 0
    
    def _process_consultation_documents(self, consultation_id: int, force_reprocess: bool = False) -> int:
        """
        Process documents for a consultation with integrated pipeline.
        
        Args:
            consultation_id: ID of consultation to process
            force_reprocess: Whether to reprocess existing content
            
        Returns:
            int: Number of documents processed
        """
        try:
            with create_database_connection(self.database_path) as conn:
                cursor = conn.cursor()
                
                # Get documents that need processing (exclude law_draft type)
                if force_reprocess:
                    query = """
                        SELECT id, type, url, content FROM documents 
                        WHERE consultation_id = ? AND type != 'law_draft'
                    """
                else:
                    query = """
                        SELECT id, type, url, content FROM documents 
                        WHERE consultation_id = ? AND type != 'law_draft'
                        AND content_cleaned IS NULL
                    """
                
                cursor.execute(query, (consultation_id,))
                documents = cursor.fetchall()
                
                if not documents:
                    self.logger.info("No documents need processing")
                    return 0
                
                self.logger.info(f"Processing {len(documents)} documents")
                processed_count = 0
                
                for doc_id, doc_type, doc_url, existing_content in documents:
                    try:
                        content = None
                        content_type = "text"
                        
                        # Determine how to get content
                        if existing_content and existing_content.strip():
                            # Use existing content if available
                            content = existing_content
                            content_type = "text"
                            self.logger.info(f"Processing document {doc_id} with existing content")
                        elif doc_url and doc_url.strip():
                            # Download and extract PDF content
                            content = doc_url  # For PDF processing, pass the URL
                            content_type = "pdf"
                            self.logger.info(f"Processing document {doc_id} by downloading PDF from {doc_url}")
                        else:
                            self.logger.warning(f"Document {doc_id} has no content or URL to process")
                            continue
                        
                        if content:
                            # Process through integrated pipeline (download → extract → clean)
                            result = self.content_processor.process_content_pipeline(content, content_type)
                            
                            # Check if we got meaningful results
                            if result.cleaned_content or result.original_content:
                                # Update database with results (single write)
                                cursor.execute("""
                                    UPDATE documents 
                                    SET content = ?, content_cleaned = ?, badness_score = ?, 
                                        greek_percentage = ?, english_percentage = ?,
                                        extraction_method = ?
                                    WHERE id = ?
                                """, (
                                    result.original_content, result.cleaned_content, result.badness_score,
                                    result.greek_percentage, result.english_percentage,
                                    result.extraction_method, doc_id
                                ))
                                
                                processed_count += 1
                                self.logger.info(f"Successfully processed document {doc_id}")
                            else:
                                self.logger.warning(f"Document {doc_id} processing produced no content")
                            
                            if processed_count % 5 == 0:
                                conn.commit()
                                self.logger.info(f"Processed {processed_count}/{len(documents)} documents")
                    
                    except Exception as e:
                        self.logger.error(f"Error processing document {doc_id}: {e}")
                
                conn.commit()
                self.logger.info(f"Completed processing {processed_count} documents")
                return processed_count
                
        except Exception as e:
            self.logger.error(f"Error processing consultation documents: {e}")
            return 0
    
    def discover_and_process_new_consultations(self) -> List[PipelineResult]:
        """
        Discover new consultations and process them through the pipeline.
        
        Returns:
            list: List of PipelineResult for each processed consultation
        """
        try:
            self.logger.info("Discovering new consultations...")
            
            # TODO: Implement discovery functionality
            # For now, return empty list
            self.logger.info("Discovery functionality not yet integrated - returning empty list")
            return []
            
        except Exception as e:
            self.logger.error(f"Error discovering new consultations: {e}")
            return []


def run_pipeline(mode: str = "single", url: Optional[str] = None, config: Optional[Dict[str, Any]] = None) -> PipelineResult:
    """
    Run the AI4Deliberation pipeline.
    
    Args:
        mode: Pipeline mode ('single', 'update', 'discover')
        url: Consultation URL (required for 'single' mode)
        config: Optional configuration dictionary
        
    Returns:
        PipelineResult: Processing results
    """
    orchestrator = PipelineOrchestrator(config)
    
    if mode == "single":
        if not url:
            raise ValueError("URL required for single consultation mode")
        return orchestrator.process_consultation(url)
    
    elif mode == "update":
        results = orchestrator.discover_and_process_new_consultations()
        # Return combined result
        total_articles = sum(r.articles_processed for r in results)
        total_documents = sum(r.documents_processed for r in results)
        total_time = sum(r.processing_time for r in results)
        all_errors = []
        for r in results:
            all_errors.extend(r.errors)
        
        return PipelineResult(
            success=len(results) > 0 and all(r.success for r in results),
            consultation_id=None,
            articles_processed=total_articles,
            documents_processed=total_documents,
            processing_time=total_time,
            errors=all_errors
        )
    
    else:
        raise ValueError(f"Unknown pipeline mode: {mode}")


def process_consultation(consultation_url: str, config: Optional[Dict[str, Any]] = None) -> PipelineResult:
    """
    Process a single consultation through the complete pipeline.
    
    Args:
        consultation_url: URL of consultation to process
        config: Optional configuration dictionary
        
    Returns:
        PipelineResult: Processing results
    """
    return run_pipeline(mode="single", url=consultation_url, config=config) 