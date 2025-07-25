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
from pathlib import Path
import argparse
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
import csv # For reading all_consultations.csv
import subprocess # For running list_consultations.py
from datetime import datetime
from sqlalchemy import create_engine, event, text, or_, and_ # Added or_, and_
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.exc import SQLAlchemyError

# Import configuration and utilities
from ai4deliberation_pipeline.config.config_manager import load_config
from ai4deliberation_pipeline.utils.logging_utils import setup_logging
from ai4deliberation_pipeline.utils.data_flow import ContentProcessor, ProcessedContent
from ai4deliberation_pipeline.utils.database import create_database_connection

# Import unified modules
from ai4deliberation_pipeline.scraper.scrape_single_consultation import scrape_and_store
from ai4deliberation_pipeline.scraper.db_models import init_db, Consultation, Article, Document

# Import the discovery function
# from scraper.list_consultations import get_all_consultations # No longer directly called, will run script

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
        
        # Paths
        self.database_path = self.config['database']['default_path']
        # Resolve repo root two levels up from this file
        self.package_root = Path(__file__).resolve().parent.parent
        self.list_consultations_script_path = self.package_root / 'scraper' / 'list_consultations.py'
        
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
        
        engine, Session = init_db(f'sqlite:///{self.database_path}')
        db_session = Session()

        try:
            self.logger.info(f"Starting pipeline processing for: {consultation_url}")
            
            consultation_id = self._scrape_consultation(consultation_url, db_session, is_new=False, selective_update=False)
            if consultation_id is None:
                errors.append("Failed to scrape consultation data")
                return PipelineResult(False, None, 0, 0, time.time() - start_time, errors)
            
            self.logger.info(f"Scraped consultation ID: {consultation_id}")
            
            articles_processed = self._process_consultation_articles(consultation_id, force_reprocess=force_reprocess)
            documents_processed = self._process_consultation_documents(consultation_id, force_reprocess=force_reprocess)
            self._clean_consultation_content(consultation_id)
            
            processing_time = time.time() - start_time
            self.logger.info(f"Pipeline completed: {articles_processed} articles, {documents_processed} documents in {processing_time:.2f}s")
            db_session.commit()
            return PipelineResult(True, consultation_id, articles_processed, documents_processed, processing_time, errors)
            
        except Exception as e:
            self.logger.error(f"Pipeline processing failed for {consultation_url}: {e}")
            errors.append(str(e))
            if db_session: db_session.rollback()
            return PipelineResult(False, consultation_id, articles_processed, documents_processed, time.time() - start_time, errors)
        finally:
            if db_session: db_session.close()
    
    def _scrape_consultation(self, url: str, session, is_new: bool = False, selective_update: bool = False) -> Optional[int]:
        """
        Scrape consultation data from URL.
        If is_new is True, it skips the initial existence check and scrapes fully.
        If selective_update is True, it attempts to update an existing record.
        Otherwise (default), it checks existence and scrapes fully if not found.
        
        Args:
            url: URL to scrape
            session: SQLAlchemy session
            is_new: If True, assume consultation is new and scrape fully.
            selective_update: If True, perform a selective update for an existing consultation.
            
        Returns:
            int: Consultation ID if successful, None otherwise
        """
        try:
            existing_consultation = None
            if not is_new: # Only check existence if not flagged as definitely new or for selective update
                self.logger.info(f"Checking if consultation for {url} already exists (is_new={is_new}, selective_update={selective_update})...")
                # Use a more robust check, possibly involving post_id if scrape_and_store can provide it early
                # For now, URL based check is kept from original logic
                normalized_url_like = f'%{url.split("?")[0]}%' 
                existing_consultation = session.query(Consultation).filter(
                    Consultation.url.like(normalized_url_like)
                ).first()

            if existing_consultation and not selective_update and not is_new:
                self.logger.info(f"Consultation already exists with ID: {existing_consultation.id} and not in selective_update/is_new mode. Skipping full scrape.")
                return existing_consultation.id
            
            if selective_update and not existing_consultation:
                self.logger.warning(f"Selective update requested for {url}, but no existing consultation found. Skipping selective update.")
                return None

            action = "selectively updating" if selective_update else "scraping brand new"
            self.logger.info(f"Proceeding with {action} for: {url}")
            
            # scrape_and_store needs the existing_cons object for selective_update
            scrape_success, scraped_data = scrape_and_store(url, session, 
                                                            selective_update=selective_update, 
                                                            existing_cons=existing_consultation if selective_update else None)
            
            if scrape_success:
                # For selective_update, scraped_data is a dict. For full scrape, it's the ID.
                if selective_update:
                    # In selective_update mode, scrape_and_store might return True even if no DB changes occur (e.g. finished consultation)
                    # We assume it handles its own commit/flush if changes are made.
                    self.logger.info(f"Selective update call for {url} reported success. Changes: {scraped_data.get('changes')}")
                    session.commit() # Ensure any changes from selective update are committed.
                    return existing_consultation.id # Return the ID of the existing, updated consultation
                else: # Full scrape (is_new=True or existing_consultation was None)
                    scraped_consultation_id = scraped_data
                    self.logger.info(f"Full scraping call successful. Returned ID: {scraped_consultation_id}")
                    if scraped_consultation_id is not None:
                        session.commit() # Ensure new consultation is committed.
                        return scraped_consultation_id
                    else:
                        self.logger.error("Full scrape reported success but no ID returned. This should not happen.")
                        session.rollback()
                        return None
            else:
                self.logger.error(f"Scraping/update call failed for URL: {url} (selective_update={selective_update})")
                session.rollback()
                return None
                    
        except Exception as e:
            self.logger.error(f"Error in _scrape_consultation for {url}: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            if session: session.rollback()
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
        self.logger.info(f"Processing articles for consultation ID: {consultation_id} (force_reprocess={force_reprocess})")
        processed_count = 0
        engine, Session = init_db(f'sqlite:///{self.database_path}') # Use local session for this self-contained part
        session = Session()
        try:
            articles_query = session.query(Article).filter(Article.consultation_id == consultation_id)
            if not force_reprocess:
                # Only process if markdown (content) is missing. Cleaning is separate.
                articles_query = articles_query.filter(Article.content == None)
            
            articles_to_process = articles_query.all()

            if not articles_to_process:
                self.logger.info(f"No articles require HTML to Markdown processing for consultation {consultation_id}.")
                return 0
            
            self.logger.info(f"Found {len(articles_to_process)} articles for HTML to Markdown processing for consultation {consultation_id}.")
            for article in articles_to_process:
                if not article.raw_html:
                    self.logger.warning(f"Article {article.id} has no raw_html. Skipping markdownification.")
                    continue
                try:
                    processed_data: ProcessedContent = self.content_processor.process_content_pipeline(article.raw_html, content_type="html")
                    article.content = processed_data.cleaned_content
                    # The title is already set on the article from the scraping phase.
                    # article.publication_date = processed_data.publication_date # Usually set by scraper
                    # article.author = processed_data.author # Usually set by scraper
                    article.updated_at = datetime.utcnow()
                    processed_count += 1
                    self.logger.debug(f"Markdownified article {article.id}.")
                except Exception as e:
                    self.logger.error(f"Error markdownifying article {article.id}: {e}", exc_info=True)
            session.commit()
            self.logger.info(f"HTML to Markdown processing complete for consultation {consultation_id}. Articles updated: {processed_count}")
            return processed_count
        except Exception as e:
            self.logger.error(f"Error in _process_consultation_articles for {consultation_id}: {e}", exc_info=True)
            if session: session.rollback()
            return 0
        finally:
            if session: session.close()
    
    def _process_consultation_documents(self, consultation_id: int, force_reprocess: bool = False) -> int:
        """
        Process documents for a consultation with integrated pipeline.
        Downloads, extracts text, and prepares for cleaning.
        
        Args:
            consultation_id: ID of consultation to process
            force_reprocess: Whether to reprocess existing content
            
        Returns:
            int: Number of documents processed
        """
        self.logger.info(f"Processing documents for consultation ID: {consultation_id} (force_reprocess={force_reprocess})")
        processed_doc_count = 0
        engine, Session = init_db(f'sqlite:///{self.database_path}') # Use local session
        session = Session()
        try:
            docs_query = session.query(Document).filter(Document.consultation_id == consultation_id)
            if not force_reprocess:
                # Only process if status indicates pending download, or download/processing failed, or text not extracted
                # OR if it was previously skipped but now might be processable (e.g. due to new URL pattern matching)
                docs_query = docs_query.filter(
                    or_(
                        Document.status.in_(['pending', 'download_failed', 'processing_failed', 'processing_skipped']),
                        and_(
                            Document.status == 'downloaded',
                            Document.processed_text == None
                        )
                    )
                )
            documents_to_process = docs_query.all()

            if not documents_to_process:
                self.logger.info(f"No documents require download/text extraction for consultation {consultation_id}.")
                return 0

            self.logger.info(f"Found {len(documents_to_process)} documents for download/text extraction for consultation {consultation_id}.")

            for doc in documents_to_process:
                self.logger.info(f"Processing document {doc.id} (URL: {doc.url})...")
                downloaded_path = None
                extracted_text = None
                doc_updated = False

                try:
                    # TODO: Add more robust content type detection here (e.g., HEAD request for Content-Type)
                    is_pdf_url = doc.url and doc.url.lower().endswith('.pdf')
                    is_download_monitor_url = doc.url and 'download.php?id=' in doc.url.lower()

                    if is_pdf_url or is_download_monitor_url:
                        self.logger.info(f"Attempting to process document {doc.id} as PDF (URL: {doc.url})")
                        extracted_text = self.content_processor.process_pdf_content(doc.url)
                        
                        # process_pdf_content in ContentProcessor is expected to return:
                        # - Extracted text (str, possibly empty if PDF had no text or extraction was poor)
                        # - Empty string (\"\") if download failed or if the downloaded file was not a processable PDF by GlossAPI
                        # - It should not return None unless a very unexpected error occurs before download/extraction attempt.

                        if extracted_text is not None and extracted_text != "": # Successfully extracted some text
                            doc.processed_text = extracted_text
                            # Try to get actual content type from processor if it stored it
                            doc.content_type = getattr(self.content_processor, 'last_downloaded_content_type', 'application/pdf')
                            doc.extraction_method = self.content_processor.config.get('pdf_processing', {}).get('docling_provider', 'docling_glossapi')
                            doc.status = 'processed'
                            self.logger.info(f"Successfully processed document {doc.id}, extracted {len(extracted_text)} chars. Content-Type: {doc.content_type}")
                        elif extracted_text == "": # Download or extraction failed, but was handled by process_pdf_content
                            doc.status = 'processing_failed'
                            # Try to get actual content type from processor if it stored it
                            doc.content_type = getattr(self.content_processor, 'last_downloaded_content_type', 'unknown')
                            self.logger.warning(f"Processing document {doc.id} resulted in empty text. Download or extraction likely failed or file was not a PDF. Status set to 'processing_failed'. Content-Type: {doc.content_type}")
                        else: # extracted_text is None - indicates a more severe issue
                            doc.status = 'processing_failed'
                            doc.content_type = getattr(self.content_processor, 'last_downloaded_content_type', 'unknown')
                            self.logger.error(f"Document {doc.id} processing failed critically (extracted_text is None). Content-Type: {doc.content_type}")
                    else:
                        self.logger.warning(f"Skipping document {doc.id}: URL does not appear to be a direct PDF or a known download link ({doc.url})")
                        doc.status = 'processing_skipped'

                    doc.updated_at = datetime.utcnow()
                    session.add(doc) # Add to session for SQLAlchemy to track changes
                    doc_updated = True
                    processed_doc_count +=1

                except Exception as e_doc:
                    self.logger.error(f"Error processing document {doc.id}: {e_doc}", exc_info=True)
                    if doc: # Ensure doc object exists
                        doc.status = 'processing_failed'
                        doc.updated_at = datetime.utcnow()
                        session.add(doc)
                        doc_updated = True # Mark as updated to attempt commit
                    if session: session.rollback() # Rollback this specific doc's transaction part if possible
                    # Continue to next document if one fails
                
                # Commit after each document to save progress, or handle as a batch
                if doc_updated:
                    try:
                        session.commit()
                    except SQLAlchemyError as e_commit:
                        self.logger.error(f"Failed to commit changes for document {doc.id}: {e_commit}")
                        session.rollback()

            self.logger.info(f"Document download/text extraction stage complete for consultation {consultation_id}. Documents handled: {processed_doc_count}")
            return processed_doc_count
        
        except SQLAlchemyError as e:
            self.logger.error(f"Database error during document processing for consultation {consultation_id}: {e}")
            if session: session.rollback()
            return 0 # Indicate failure or no documents processed
        except Exception as e_main:
            self.logger.error(f"Unexpected error in _process_consultation_documents for consultation {consultation_id}: {e_main}", exc_info=True)
            if session: session.rollback()
            return 0
        finally:
            if session: session.close()

    def _clean_consultation_content(self, consultation_id: int):
        """
        Clean textual content (articles, processed documents) for a consultation 
        using the Rust-based text cleaner.
        
        Args:
            consultation_id: ID of the consultation whose content needs cleaning.
        """
        self.logger.info(f"Starting text cleaning for consultation ID: {consultation_id}")
        items_cleaned_count = 0
        
        if not hasattr(self.content_processor, 'rust_text_cleaner') or self.content_processor.rust_text_cleaner is None:
            self.logger.error("Rust text cleaner is not available in ContentProcessor. Skipping cleaning.")
            return

        engine, Session = init_db(f'sqlite:///{self.database_path}') # Use local session
        session = Session()

        try:
            rust_version_date = self.config.get('rust_cleaner_version_date', '1970-01-01')

            # 1. Clean Articles
            self.logger.debug(f"Fetching articles for consultation {consultation_id} to clean.")
            article_query_sql = text(f"""
                SELECT id, content
                FROM articles
                WHERE consultation_id = :cid 
                AND content IS NOT NULL AND content != ''
                AND (content_cleaned IS NULL OR content_cleaned = '')
            """)
            articles_to_clean = session.execute(article_query_sql, {'cid': consultation_id}).fetchall()
            self.logger.info(f"Found {len(articles_to_clean)} articles to clean for consultation {consultation_id}.")

            for article_id, raw_text_content in articles_to_clean:
                if not raw_text_content: # Should be caught by query, but double check
                    continue
                try:
                    cleaned_text, badness_score, greek_percentage, english_percentage = \
                        self.content_processor.clean_text_for_pipeline(
                            raw_text_content,
                            item_type="article",
                            item_id=article_id,
                            consultation_id=consultation_id
                        )

                    update_sql = text(f"""
                        UPDATE articles 
                        SET content_cleaned = :cc, badness_score = :bs, 
                            greek_percentage = :gp, english_percentage = :ep, 
                            updated_at = :ua
                        WHERE id = :id
                    """)
                    session.execute(update_sql, {
                        'cc': cleaned_text, 'bs': badness_score, 
                        'gp': greek_percentage, 'ep': english_percentage, 
                        'ua': datetime.utcnow(), 'id': article_id
                    })
                    items_cleaned_count += 1
                    self.logger.debug(f"Cleaned article {article_id}. Score: {badness_score:.3f}")
                except Exception as e:
                    self.logger.error(f"Error cleaning article {article_id}: {e}", exc_info=True)
                    # Optionally, mark as error or skip

            # 2. Clean Processed Document Texts
            self.logger.debug(f"Fetching processed document texts for consultation {consultation_id} to clean.")
            document_query_sql = text(f"""
                SELECT id, processed_text 
                FROM documents
                WHERE consultation_id = :cid 
                AND processed_text IS NOT NULL AND processed_text != ''
                AND (content_cleaned IS NULL OR content_cleaned = '')
            """)
            documents_to_clean = session.execute(document_query_sql, {'cid': consultation_id}).fetchall()
            self.logger.info(f"Found {len(documents_to_clean)} document texts to clean for consultation {consultation_id}.")

            for doc_id, raw_processed_text in documents_to_clean:
                if not raw_processed_text: # Should be caught by query
                    continue
                try:
                    cleaned_text, badness_score, greek_percentage, english_percentage = \
                        self.content_processor.clean_text_for_pipeline(
                            raw_processed_text,
                            item_type="document",
                            item_id=doc_id,
                            consultation_id=consultation_id
                        )

                    update_sql = text(f"""
                        UPDATE documents
                        SET content_cleaned = :cc, badness_score = :bs, 
                            greek_percentage = :gp, english_percentage = :ep, 
                            updated_at = :ua
                        WHERE id = :id
                    """)
                    session.execute(update_sql, {
                        'cc': cleaned_text, 'bs': badness_score, 
                        'gp': greek_percentage, 'ep': english_percentage, 
                        'ua': datetime.utcnow(), 'id': doc_id
                    })
                    items_cleaned_count += 1
                    self.logger.debug(f"Cleaned document text {doc_id}. Score: {badness_score:.3f}")
                except Exception as e:
                    self.logger.error(f"Error cleaning document text {doc_id}: {e}", exc_info=True)
            
            session.commit()
            self.logger.info(f"Content cleaning completed for consultation {consultation_id}. Total items (re)cleaned: {items_cleaned_count}.")

        except Exception as e:
            self.logger.error(f"Database error during content cleaning for consultation {consultation_id}: {e}")
            import traceback
            self.logger.error(traceback.format_exc())

    def discover_and_process_new_consultations(self) -> List[PipelineResult]:
        """
        Discover new consultations and process them through the pipeline.
        
        Returns:
            list: List of PipelineResult for each processed consultation
        """
        results: List[PipelineResult] = []
        self.logger.info("Discovering new consultations...")

        # Step 1: Run scraper/list_consultations.py --update
        try:
            self.logger.info(f"Running {self.list_consultations_script_path} --update to refresh all_consultations.csv")
            process = subprocess.run(
                [sys.executable, self.list_consultations_script_path, "--update"],
                capture_output=True, text=True, check=False, encoding='utf-8' # Added encoding
            )
            if process.returncode != 0:
                self.logger.error(f"list_consultations.py script failed. STDERR: {process.stderr} STDOUT: {process.stdout}")
            else:
                self.logger.info(f"list_consultations.py output:\n{process.stdout}")
        except Exception as e_subproc:
             self.logger.error(f"Failed to run list_consultations.py: {e_subproc}", exc_info=True)
             return results # Cannot proceed if discovery script fails

        # Step 2: Read all_consultations.csv
        all_site_consultations_data = []
        csv_path = self.package_root / 'all_consultations.csv'
        if not os.path.exists(csv_path):
            self.logger.error(f"all_consultations.csv not found at {csv_path}. Cannot proceed.")
            return results
        
        with open(csv_path, 'r', newline='', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                all_site_consultations_data.append(row)
        
        if not all_site_consultations_data:
            self.logger.info("No consultations found in all_consultations.csv. Checking for unfinished in DB.")
        else:
            self.logger.info(f"Found {len(all_site_consultations_data)} total consultations from opengov.gr listing.")

        engine, Session = init_db(f'sqlite:///{self.database_path}')
        db_session = Session()
        try:
            # Step 3: Get existing consultation URLs from DB for comparison
            # Use full URLs for more precise checking
            existing_consultation_urls = {res[0] for res in db_session.query(Consultation.url).all()}
            self.logger.info(f"Found {len(existing_consultation_urls)} unique consultation URLs in the database for exact matching.")

            # Step 4: Identify and process truly new consultations
            new_consultations_processed_count = 0
            for csv_entry in all_site_consultations_data:
                url_from_csv = csv_entry['url']
                # No normalization here, compare the full URL
                # normalized_url_from_csv = url_from_csv.split('?')[0] # Old logic

                if url_from_csv not in existing_consultation_urls:
                    self.logger.info(f"New consultation identified by full URL: {url_from_csv} (Title: {csv_entry.get('title', 'N/A')}). Processing...")
                    start_time_single = time.time()
                    try:
                        # For new consultations, we pass is_new=True
                        # The _scrape_consultation method will use the db_session
                        new_consult_id = self._scrape_consultation(url_from_csv, db_session, is_new=True)
                        
                        if new_consult_id:
                            db_session.flush() # Ensure ID is available if new
                            self.logger.info(f"Successfully scraped new consultation {url_from_csv}, assigned/found ID: {new_consult_id}")
                            articles_p = self._process_consultation_articles(new_consult_id, force_reprocess=True)
                            docs_p = self._process_consultation_documents(new_consult_id, force_reprocess=True)
                            self._clean_consultation_content(new_consult_id)
                            db_session.commit() # Commit all changes for this new consultation
                            results.append(PipelineResult(True, new_consult_id, articles_p, docs_p, time.time() - start_time_single, []))
                            existing_consultation_urls.add(url_from_csv) # Add the full URL to the set of processed ones
                            new_consultations_processed_count += 1
                        else:
                            db_session.rollback() # Rollback if scraping failed for the new item
                            self.logger.error(f"Failed to scrape new consultation: {url_from_csv}")
                            results.append(PipelineResult(False, None, 0, 0, time.time() - start_time_single, [f"Failed to scrape new: {url_from_csv}"]))
                    except Exception as e_new_proc:
                        db_session.rollback()
                        self.logger.error(f"Major error processing new consultation {url_from_csv}: {e_new_proc}", exc_info=True)
                        results.append(PipelineResult(False, None, 0, 0, time.time() - start_time_single, [f"Major error processing new: {url_from_csv}, {e_new_proc}"]))
            self.logger.info(f"Finished processing new consultations. Processed and added: {new_consultations_processed_count}")

            # Step 5: Identify and update unfinished consultations from DB
            self.logger.info("Identifying and selectively updating unfinished consultations from DB...")
            unfinished_consultations = db_session.query(Consultation).filter(Consultation.is_finished == False).all()
            unfinished_updated_count = 0

            if not unfinished_consultations:
                self.logger.info("No unfinished consultations found in the database to update.")
            else:
                self.logger.info(f"Found {len(unfinished_consultations)} unfinished consultations to check for updates.")
                for consult_to_update in unfinished_consultations:
                    self.logger.info(f"Checking for updates for unfinished ID: {consult_to_update.id}, URL: {consult_to_update.url}")
                    start_time_single = time.time()
                    try:
                        # Selective update will handle metadata, new comments, and is_finished status
                        # It uses the same db_session
                        updated_id = self._scrape_consultation(consult_to_update.url, db_session, selective_update=True)
                        
                        if updated_id: # Indicates selective scrape ran
                            # Potentially new comments/articles were added by scrape_and_store.
                            # We need to process their HTML to Markdown and then clean them.
                            self.logger.info(f"Selective update for {consult_to_update.url} (ID: {updated_id}) ran. Processing potential new content...")
                            articles_p = self._process_consultation_articles(updated_id, force_reprocess=False) # Process only if content is missing
                            # For documents, selective_update usually doesn't add new ones, but if it did, this would catch them.
                            docs_p = self._process_consultation_documents(updated_id, force_reprocess=False)
                            # Re-clean all content for this consultation in case badness scores or other things changed,
                            # or if new articles/comments were added and need cleaning.
                            self._clean_consultation_content(updated_id)
                            db_session.commit() # Commit changes from selective update and subsequent processing
                            unfinished_updated_count += 1
                            results.append(PipelineResult(True, updated_id, articles_p, docs_p, time.time() - start_time_single, []))
                        else:
                            # _scrape_consultation with selective_update might return None if it logs an issue or finds no existing.
                            # No rollback needed here as _scrape_consultation handles its own or doesn't make changes if it returns None.
                            self.logger.info(f"Selective update for {consult_to_update.url} (ID: {consult_to_update.id}) did not proceed or made no direct DB ID change.")
                            # Still append a result to show it was checked
                            results.append(PipelineResult(True, consult_to_update.id, 0,0, time.time()-start_time_single, ["Selective update ran but no new ID returned/no changes requiring ID confirmation."]))

                    except Exception as e_unfinished_proc:
                        db_session.rollback()
                        self.logger.error(f"Major error during selective update for {consult_to_update.url}: {e_unfinished_proc}", exc_info=True)
                        results.append(PipelineResult(False, consult_to_update.id, 0,0, time.time()-start_time_single, [f"Major error processing unfinished: {consult_to_update.url}, {e_unfinished_proc}"]))
                self.logger.info(f"Finished checking/updating unfinished consultations. Handled: {len(unfinished_consultations)}")
        except Exception as e_outer_discovery:
            self.logger.error(f"Outer error during discovery and processing: {e_outer_discovery}", exc_info=True)
            if db_session: db_session.rollback() # Rollback any partial changes if loop fails
            results.append(PipelineResult(False, None, 0, 0, 0, [str(e_outer_discovery)]))
        finally:
            if db_session: db_session.close()
        
        self.logger.info("Consultation discovery and update process finished.")
        return results

# Wrapper functions for main execution block
def run_pipeline_entry(mode: str = "single", url: Optional[str] = None, config_dict: Optional[Dict[str, Any]] = None, force_reprocess: bool = False):
    orchestrator = PipelineOrchestrator(config_dict)
    if mode == "single":
        if not url:
            raise ValueError("URL required for single consultation mode")
        return orchestrator.process_consultation(url, force_reprocess=force_reprocess)
    elif mode == "update":
        return orchestrator.discover_and_process_new_consultations() # This returns a list
    else:
        raise ValueError(f"Unknown pipeline mode: {mode}")

def main():
    parser = argparse.ArgumentParser(description="AI4Deliberation Pipeline Orchestrator")
    parser.add_argument("--mode", type=str, default="update", choices=["single", "update"],
                        help="Pipeline mode: 'single' for one URL, 'update' for discovery and update.")
    parser.add_argument("--url", type=str, help="URL to process (for single mode)")
    parser.add_argument("--force-reprocess", action="store_true", help="Force reprocessing of all content for the given URL/consultation.")
    parser.add_argument("--sync-db", action="store_true", help="Download, anonymise, and upload DB before executing pipeline.")
    
    args = parser.parse_args()
    cfg = load_config()
    logger = setup_logging(cfg, "orchestrator_main_script")

    # Optional DB sync before pipeline run
    if args.sync_db:
        try:
            from ai4deliberation_pipeline.utils.anonymizer import ensure_download_anonymise_upload
            repo_id = "glossAPI/opengov.gr-diaboyleuseis"
            filename = cfg['database']['default_path']
            local_dir = os.path.dirname(filename) if os.path.dirname(filename) else os.getcwd()
            logger.info("--sync-db flag detected. Running DB sync (download → anonymise → upload)…")
            ensure_download_anonymise_upload(repo_id, filename, local_dir)
        except Exception as sync_err:
            logger.error(f"DB sync failed: {sync_err}")
 
    

    logger.info(f"Running orchestrator in mode: {args.mode}")
    if args.mode == 'single' and args.url:
        logger.info(f"Processing single URL: {args.url}")
    
    try:
        post_pipeline_upload_needed = args.sync_db

        if args.mode == "update":
            list_of_results = run_pipeline_entry(mode=args.mode, config_dict=cfg) # Expecting a list
            logger.info("Update mode finished.")
            if post_pipeline_upload_needed:
                try:
                    from ai4deliberation_pipeline.utils.anonymizer import anonymise_sqlite, upload_db_to_hf
                    anonymise_sqlite(filename)
                    upload_db_to_hf(repo_id, filename)
                except Exception as up_err:
                    logger.error(f"Post-pipeline upload failed: {up_err}")
            print(f"Update mode processing results: {len(list_of_results)} operations attempted.")
            for res_idx, res_item in enumerate(list_of_results):
                print(f"Result {res_idx + 1}: {res_item}")
            sys.exit(0) # Assume 0 for update mode unless catastrophic failure in run_pipeline_entry
        else: # single mode
            pipeline_result_obj = run_pipeline_entry(mode=args.mode, url=args.url, config_dict=cfg, force_reprocess=args.force_reprocess)
            print(f"Single mode processing result: {pipeline_result_obj}")
            if post_pipeline_upload_needed:
                try:
                    from ai4deliberation_pipeline.utils.anonymizer import anonymise_sqlite, upload_db_to_hf
                    anonymise_sqlite(filename)
                    upload_db_to_hf(repo_id, filename)
                except Exception as up_err:
                    logger.error(f"Post-pipeline upload failed: {up_err}")
            sys.exit(0 if pipeline_result_obj.success else 1)

    except ValueError as ve:
        logger.error(f"Configuration or argument error: {ve}", exc_info=True)
        sys.exit(2)
    except Exception as e:
        logger.error(f"An unexpected error occurred in the orchestrator main script: {e}", exc_info=True)
        sys.exit(3) 

if __name__ == "__main__":
    main() 