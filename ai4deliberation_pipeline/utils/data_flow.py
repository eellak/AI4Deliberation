#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Efficient Data Flow Processor

Handles content processing in memory to avoid inefficient database read/write cycles.
Pipeline flow: extract → clean → store once
"""

import os
import logging
import tempfile
import time
import requests
import subprocess
import sys
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from urllib.parse import urlparse
from pathlib import Path


@dataclass
class ProcessedContent:
    """Data class for processed content with all pipeline results."""
    original_content: str
    cleaned_content: str
    badness_score: float
    greek_percentage: float
    english_percentage: float
    extraction_method: str = "pipeline"
    processing_time: float = 0.0


@dataclass
class DocumentToProcess:
    """Data class for documents that need processing."""
    document_id: int
    document_type: str
    url: str
    raw_content: Optional[str] = None


class ContentProcessor:
    """
    Efficient content processor that handles the full pipeline in memory.
    
    This class implements the efficient pipeline flow:
    1. Extract content (PDF download and extraction or HTML)
    2. Clean content with Rust
    3. Store final results in database (single write)
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize content processor with configuration.
        
        Args:
            config: Pipeline configuration dictionary
        """
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # Initialize processors to None initially
        self.rust_text_cleaner = None
        self.markdownify = None
        self.Corpus = None # For GlossAPI PDF extraction
        self.pd = None # Pandas for GlossAPI

        # Set up directories
        self.temp_processing = config['directories']['temp_processing']
        self.pdfs_dir = config['directories']['pdfs']
        self.markdown_dir = config['directories']['markdown']
        
        # Create directories
        os.makedirs(self.pdfs_dir, exist_ok=True)
        os.makedirs(self.markdown_dir, exist_ok=True)
        
        # Import processing modules
        self._setup_processors()
    
    def _setup_processors(self):
        """Setup the processing modules. Failures are logged but don't stop ContentProcessor instantiation."""
        # Ensure the glossapi editable install path is discoverable
        glossapi_parent_dir = "/mnt/data/glossAPI"
        if glossapi_parent_dir not in sys.path:
            sys.path.insert(0, glossapi_parent_dir) # Insert at the beginning for priority

        try:
            # Import Rust text cleaner
            import text_cleaner_rs
            self.rust_text_cleaner = text_cleaner_rs
            self.logger.info("Successfully imported and assigned text_cleaner_rs.")
        except ImportError as e:
            self.logger.error(f"Failed to import text_cleaner_rs: {e}. Rust cleaner will NOT be available.")
            # self.rust_text_cleaner remains None
        
        try:
            # Import markdownify for HTML processing
            import markdownify
            self.markdownify = markdownify
            self.logger.info("Successfully imported markdownify.")
        except ImportError as e:
            self.logger.error(f"Failed to import markdownify: {e}. HTML to Markdown processing will NOT be available.")
            # self.markdownify remains None

        try:
            # Attempt to import GlossAPI and pandas for PDF processing
            # This is an optional component, so failure is not fatal to ContentProcessor
            # but will limit PDF processing capabilities.
            # Check if glossapi is enabled in config
            if self.config.get('pdf_processing', {}).get('docling_provider', '').lower() == 'glossapi':
                try:
                    from glossapi.corpus import Corpus
                    self.Corpus = Corpus
                    import pandas as pd
                    self.pd = pd
                    self.logger.info("Successfully imported GlossAPI (Corpus) and pandas for PDF processing.")
                except ImportError as e_glossapi:
                    self.logger.warning(f"GlossAPI or pandas could not be imported: {e_glossapi}. PDF extraction via GlossAPI will not be available.")
                    self.Corpus = None
                    self.pd = None
                    # Check for custom path if primary import fails
                    glossapi_path = self.config.get('pdf_processing', {}).get('glossapi_custom_path')
                    if glossapi_path and os.path.exists(glossapi_path):
                        if glossapi_path not in sys.path:
                            sys.path.append(glossapi_path)
                        try:
                            from glossapi.corpus import Corpus
                            self.Corpus = Corpus
                            # Pandas should be a general dependency, try importing again if Corpus succeeded from custom path
                            import pandas as pd 
                            self.pd = pd
                            self.logger.info(f"Successfully imported GlossAPI (Corpus) and pandas from custom path: {glossapi_path}")
                        except ImportError as e_custom_glossapi:
                            self.logger.warning(f"Failed to import GlossAPI or pandas even from custom path {glossapi_path}: {e_custom_glossapi}")
                            self.Corpus = None
                            self.pd = None 
            else:
                self.logger.info("GlossAPI PDF processing is not enabled in config. Skipping GlossAPI import attempt.")

        except Exception as e_setup:
            self.logger.error(f"An unexpected error occurred during _setup_processors: {e_setup}")
    
    def download_pdf(self, url: str, filename: str) -> Optional[str]:
        """
        Download PDF from URL to local file.
        
        Args:
            url: PDF URL to download
            filename: Local filename to save as
            
        Returns:
            str: Path to downloaded file or None if failed
        """
        try:
            # Get download configuration
            download_config = self.config.get('pdf_processing', {}).get('download', {})
            timeout = download_config.get('timeout', 60)
            max_size = download_config.get('max_size', 100) * 1024 * 1024  # Convert MB to bytes
            chunk_size = download_config.get('chunk_size', 8192)
            
            filepath = os.path.join(self.pdfs_dir, filename)
            
            self.logger.info(f"Downloading PDF from {url}")
            
            # Make request with timeout
            response = requests.get(url, stream=True, timeout=timeout, allow_redirects=True)
            response.raise_for_status()
            
            # Check content length
            content_length = response.headers.get('content-length')
            if content_length and int(content_length) > max_size:
                self.logger.error(f"PDF too large: {content_length} bytes > {max_size} bytes")
                return None
            
            # Download in chunks
            downloaded = 0
            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        
                        # Check size limit during download
                        if downloaded > max_size:
                            self.logger.error(f"PDF too large during download: {downloaded} bytes")
                            os.remove(filepath)
                            return None
            
            self.logger.info(f"Downloaded PDF: {downloaded} bytes to {filepath}")
            return filepath
            
        except Exception as e:
            self.logger.error(f"Error downloading PDF from {url}: {e}")
            return None
    
    def extract_pdf_with_glossapi(self, pdf_path: str) -> Optional[str]:
        """
        Extract text from PDF using GlossAPI.
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            str: Extracted text content or None if failed
        """
        if not self.Corpus or not self.pd:
            self.logger.error("GlossAPI (Corpus) or pandas (pd) not available. Cannot extract PDF with GlossAPI.")
            return None
        
        try:
            # Create temporary workspace for this PDF
            with tempfile.TemporaryDirectory(prefix='pdf_extraction_') as temp_workspace:
                # Create a simple DataFrame with just this PDF
                # import pandas as pd # Use self.pd
                
                pdf_df = self.pd.DataFrame({
                    'document_id': [1],
                    'redirected_url': [f'file://{pdf_path}']
                })
                
                # Save to parquet for GlossAPI
                parquet_path = os.path.join(temp_workspace, 'documents.parquet')
                pdf_df.to_parquet(parquet_path, index=False)
                
                # Create GlossAPI Corpus
                corpus = self.Corpus( # Use self.Corpus
                    input_dir=temp_workspace,
                    output_dir=temp_workspace,
                    verbose=False
                )
                
                # Since we already have the file locally, just extract it
                # Skip download and go straight to extraction
                self.logger.info(f"Extracting PDF with GlossAPI: {pdf_path}")
                
                # Copy the PDF to the expected location in the workspace
                # GlossAPI expects the files to be in a 'downloads' subdirectory within its input_dir
                glossapi_downloads_dir = os.path.join(temp_workspace, 'downloads') 
                os.makedirs(glossapi_downloads_dir, exist_ok=True)
                
                import shutil
                pdf_name = os.path.basename(pdf_path)
                workspace_pdf_path = os.path.join(glossapi_downloads_dir, pdf_name)
                shutil.copy2(pdf_path, workspace_pdf_path)
                
                # Run extraction
                corpus.extract(num_threads=1)
                
                # Read the extracted content
                markdown_dir = os.path.join(temp_workspace, 'markdown')
                if os.path.exists(markdown_dir):
                    # Find the markdown file for our PDF
                    pdf_basename = os.path.splitext(pdf_name)[0]
                    markdown_file = os.path.join(markdown_dir, f"{pdf_basename}.md")
                    
                    if os.path.exists(markdown_file):
                        with open(markdown_file, 'r', encoding='utf-8') as f:
                            extracted_content = f.read().strip()
                        
                        if extracted_content:
                            self.logger.info(f"Successfully extracted {len(extracted_content)} characters from PDF")
                            return extracted_content
                        else:
                            self.logger.warning(f"PDF extraction produced empty content: {pdf_path}")
                            return ""
                    else:
                        self.logger.warning(f"No markdown file created for PDF: {pdf_path}")
                        return ""
                else:
                    self.logger.warning(f"No markdown directory created for PDF: {pdf_path}")
                    return ""
                
        except Exception as e:
            self.logger.error(f"Error extracting PDF {pdf_path}: {e}")
            return None
    
    def process_html_content(self, html_content: str) -> str:
        """
        Process HTML content to markdown.
        
        Args:
            html_content: Raw HTML content
            
        Returns:
            str: Cleaned markdown content
        """
        if not html_content or not html_content.strip():
            return ""
        
        try:
            # Get markdownify settings from config
            md_config = self.config.get('html_processing', {}).get('markdownify', {})
            
            # Convert HTML to markdown
            markdown_content = self.markdownify.markdownify(
                html_content,
                heading_style=md_config.get('heading_style', 'ATX'),
                bullets=md_config.get('bullets', '*'),
                emphasis_mark=md_config.get('emphasis_mark', '_'),
                strong_mark=md_config.get('strong_mark', '**'),
                wrap=md_config.get('wrap', False),
                wrap_width=md_config.get('wrap_width', 80),
                strip=md_config.get('convert_truefalse', ['b', 'strong', 'i', 'em', 'u', 'mark'])
            )
            
            return markdown_content.strip() if markdown_content else ""
            
        except Exception as e:
            self.logger.error(f"Error converting HTML to markdown: {e}")
            return ""
    
    def process_pdf_content(self, pdf_url: str) -> str:
        """
        Download and extract content from PDF URL.
        
        Args:
            pdf_url: URL of PDF to download and extract
            
        Returns:
            str: Extracted text content
        """
        if not pdf_url or not pdf_url.strip():
            return ""
        
        try:
            # Generate filename from URL
            parsed_url = urlparse(pdf_url)
            filename = os.path.basename(parsed_url.path)
            if not filename or not filename.endswith('.pdf'):
                # Generate filename from URL hash
                import hashlib
                url_hash = hashlib.md5(pdf_url.encode()).hexdigest()[:8]
                filename = f"document_{url_hash}.pdf"
            
            # Download PDF
            pdf_path = self.download_pdf(pdf_url, filename)
            if not pdf_path:
                self.logger.error(f"Failed to download PDF: {pdf_url}")
                return ""
            
            # Extract text with GlossAPI
            extracted_content = self.extract_pdf_with_glossapi(pdf_path)
            if extracted_content is None:
                self.logger.error(f"Failed to extract content from PDF: {pdf_path}")
                return ""
            
            return extracted_content
            
        except Exception as e:
            self.logger.error(f"Error processing PDF content from {pdf_url}: {e}")
            return ""
    
    def clean_content_with_rust(self, content: str) -> Tuple[str, float, float, float]:
        """
        Clean content using Rust text cleaner.
        
        Args:
            content: Raw content to clean
            
        Returns:
            tuple: (cleaned_content, badness_score, greek_percentage, english_percentage)
        """
        if not content or not content.strip():
            return "", 1.0, 0.0, 0.0  # Bad score for empty content
        
        try:
            with tempfile.TemporaryDirectory(prefix='content_cleaning_') as temp_dir:
                # Create temporary files
                input_file = os.path.join(temp_dir, 'input.md')
                output_dir = os.path.join(temp_dir, 'output')
                output_file = os.path.join(output_dir, 'input.md')  # Rust cleaner uses same filename
                csv_file = os.path.join(temp_dir, 'analysis.csv')
                
                # Ensure output directory exists
                os.makedirs(output_dir, exist_ok=True)
                
                # Write content to temporary file
                with open(input_file, 'w', encoding='utf-8') as f:
                    f.write(content)
                
                # Get Rust cleaner settings
                rust_config = self.config.get('rust_cleaner', {})
                scripts_from_config = rust_config.get('scripts', 'lat,grc').split(',')
                threads = rust_config.get('threads', 4)
                
                # Map script names for Rust compatibility
                user_scripts_mapped = []
                for s_config in scripts_from_config:
                    if s_config.lower() == 'lat':
                        user_scripts_mapped.append('latin')
                    elif s_config.lower() == 'grc':
                        user_scripts_mapped.append('greek')
                    else:
                        user_scripts_mapped.append(s_config)

                # Prepare scripts (ensure base scripts are included)
                # Base scripts are those essential for basic cleaning and analysis context.
                base_scripts = ["punctuation", "numbers", "common_symbols"]
                
                # Combine mapped user scripts with base scripts, ensuring uniqueness
                # The Rust side expects keys like "latin", "greek", "punctuation", etc.
                final_scripts = list(set(user_scripts_mapped + base_scripts))
                self.logger.debug(f"Final scripts being passed to Rust cleaner: {final_scripts}")
                
                # Run Rust text cleaner
                self.rust_text_cleaner.generate_analysis_report_for_directory(
                    os.path.dirname(input_file), # input_dir
                    csv_file,                    # output_csv_path
                    output_dir,                  # output_dir_cleaned_files
                    final_scripts,               # scripts_to_keep (now correctly mapped)
                    threads
                )
                
                # Read cleaned content - try multiple possible locations
                cleaned_content = ""
                possible_output_files = [
                    output_file,  # Standard location
                    os.path.join(output_dir, 'input.md'),  # Same name as input
                    os.path.join(temp_dir, 'input.md'),  # Direct in temp dir
                ]
                
                for possible_file in possible_output_files:
                    if os.path.exists(possible_file):
                        with open(possible_file, 'r', encoding='utf-8') as f:
                            cleaned_content = f.read().strip()
                        self.logger.info(f"Found cleaned content at: {possible_file}")
                        break
                
                # If no cleaned content found, use original content
                if not cleaned_content:
                    self.logger.warning("No cleaned content file found, using original content")
                    cleaned_content = content.strip()
                
                # Read analysis results
                badness_score = 1.0  # Default bad score
                greek_pct = 0.0
                english_pct = 0.0
                
                if os.path.exists(csv_file):
                    import pandas as pd
                    df = pd.read_csv(csv_file)
                    
                    if len(df) > 0:
                        row = df.iloc[0]
                        
                        # Expect 'File Name' from Rust cleaner CSV
                        expected_filename_col = 'File Name' 
                        if expected_filename_col not in row:
                            self.logger.error(f"'{expected_filename_col}' column not found in CSV: {csv_file}. Columns: {df.columns.tolist()}. Row data: {row.to_dict()}")
                            # Let it proceed to hit KeyError for now, as the specific catch will handle it.

                        original_input_filename = row[expected_filename_col]
                        cleaned_file_path = os.path.join(output_dir, original_input_filename)

                        if os.path.exists(cleaned_file_path):
                            with open(cleaned_file_path, 'r', encoding='utf-8') as f:
                                cleaned_text = f.read()
                            self.logger.info(f"Found cleaned content at: {cleaned_file_path}")
                        else:
                            self.logger.warning(f"Cleaned file not found at: {cleaned_file_path}. CSV row: {row.to_dict()}")
                        
                        # Extract Badness, Greek, and Latin percentages
                        # Expect 'Greek Percentage' and 'Latin Percentage' from Rust CSV
                        badness_score_str = row.get('Badness')
                        greek_percentage_str = row.get('Greek Percentage') 
                        latin_percentage_str = row.get('Latin Percentage') 
                        # english_percentage_str = row.get('English Percentage') # If Rust ever provides this specific column

                        # Convert to float, removing '%' if present
                        try:
                            badness_score = float(badness_score_str) if badness_score_str is not None else None
                            
                            if greek_percentage_str is not None:
                                greek_percentage = float(str(greek_percentage_str).replace('%', ''))
                            else:
                                greek_percentage = None
                                
                            if latin_percentage_str is not None:
                                latin_percentage = float(str(latin_percentage_str).replace('%', ''))
                            else:
                                latin_percentage = None
                            
                            # english_percentage = float(str(english_percentage_str).replace('%','')) if english_percentage_str is not None else None
                            english_percentage = None # Explicitly None for now as it's not in CSV

                        except ValueError as e:
                            self.logger.error(f"Error converting Rust cleaner stats to float: {e}. CSV row: {row.to_dict()}")
                            badness_score, greek_percentage, latin_percentage, english_percentage = None, None, None, None
                        
                    else:
                        self.logger.warning(f"Empty CSV file: {csv_file}")
                else:
                    self.logger.warning("No CSV analysis file found, using default scores")
                
                return cleaned_content, badness_score, greek_percentage, latin_percentage
                
        except KeyError as ke:
            self.logger.error(f"KeyError accessing CSV data from {csv_file if 'csv_file' in locals() else 'N/A'}: {ke}. DF Columns: {df.columns.tolist() if 'df' in locals() and hasattr(df, 'columns') else 'N/A'}. Row: {row.to_dict() if 'row' in locals() else 'N/A'}")
            return content.strip(), 1.0, 0.0, 0.0 # Fallback
        except Exception as e:
            # Log which csv_file caused the issue if it's defined
            csv_path_info = f" (CSV: {csv_file})" if 'csv_file' in locals() and os.path.exists(csv_file) else ""
            self.logger.error(f"Error cleaning content with Rust{csv_path_info}: {e}")
            # Always return the original content as fallback
            return content.strip(), 1.0, 0.0, 0.0
    
    def process_content_pipeline(self, raw_content: str, content_type: str = "html") -> ProcessedContent:
        """
        Process content through the full pipeline: extract → clean → return results.
        
        Args:
            raw_content: Raw content (HTML or extracted text)
            content_type: Type of content ("html", "pdf", or "text")
            
        Returns:
            ProcessedContent: Fully processed content with metrics
        """
        start_time = time.time()
        
        try:
            # Step 1: Extract/convert content
            if content_type == "html":
                extracted_content = self.process_html_content(raw_content)
            elif content_type == "pdf":
                extracted_content = self.process_pdf_content(raw_content)  # raw_content is path
            else:
                extracted_content = raw_content  # Already text
            
            # Step 2: Clean content with Rust
            cleaned_content, badness_score, greek_pct, latin_pct = self.clean_content_with_rust(extracted_content)
            
            processing_time = time.time() - start_time
            
            return ProcessedContent(
                original_content=extracted_content,
                cleaned_content=cleaned_content,
                badness_score=badness_score,
                greek_percentage=greek_pct,
                english_percentage=latin_pct, # Map Latin from Rust to English for ProcessedContent
                extraction_method="integrated_pipeline",
                processing_time=processing_time
            )
            
        except Exception as e:
            self.logger.error(f"Error in content pipeline: {e}")
            processing_time = time.time() - start_time
            
            # Return error result
            return ProcessedContent(
                original_content=raw_content,
                cleaned_content="",
                badness_score=1.0,
                greek_percentage=0.0,
                english_percentage=0.0,
                extraction_method="error",
                processing_time=processing_time
            )
    
    def process_multiple_contents(self, contents: List[Tuple[str, str]]) -> List[ProcessedContent]:
        """
        Process multiple contents efficiently.
        
        Args:
            contents: List of (content, content_type) tuples
            
        Returns:
            list: List of ProcessedContent results
        """
        results = []
        
        for i, (content, content_type) in enumerate(contents):
            self.logger.info(f"Processing content {i+1}/{len(contents)}")
            result = self.process_content_pipeline(content, content_type)
            results.append(result)
        
        return results 

    def clean_text_for_pipeline(self, text_content: str, item_type: str, item_id: int, consultation_id: int) -> Tuple[str, float, float, float]:
        """
        Cleans a single string of text using the Rust text_cleaner_rs module,
        by writing it to a temporary file and processing that file.
        This mimics how RustProcessor uses generate_analysis_report_for_directory.

        Args:
            text_content: The raw text string to clean.
            item_type: Type of item being cleaned (e.g., "article", "document").
            item_id: ID of the item.
            consultation_id: ID of the parent consultation.

        Returns:
            A tuple: (cleaned_text, badness_score, greek_percentage, english_percentage)
            Returns (original_text, 1.0, 0.0, 0.0) on failure.
        """
        if not self.rust_text_cleaner:
            self.logger.warning(f"Rust cleaner not available. Returning original content for {item_type} {item_id}.")
            return text_content, 1.0, 0.0, 0.0

        if not text_content or not text_content.strip():
            self.logger.info(f"No text content to clean for {item_type} {item_id}. Returning empty.")
            return "", 1.0, 0.0, 0.0
        
        # Default values for return in case of error
        default_return = (text_content, 1.0, 0.0, 0.0)

        # Rust cleaner settings from config (similar to RustProcessor)
        rust_config = self.config.get('rust_cleaner', {})
        threads = rust_config.get('threads', 1) # Default to 1 thread for single item processing
        scripts_str = rust_config.get('scripts', 'lat,grc')
        user_scripts_from_config = [s.strip() for s in scripts_str.split(',') if s.strip()]
        mapped_scripts = []
        for s_config in user_scripts_from_config:
            if s_config.lower() == 'lat': mapped_scripts.append('latin')
            elif s_config.lower() == 'grc': mapped_scripts.append('greek')
            else: mapped_scripts.append(s_config.lower())
        final_scripts_to_pass = list(set(mapped_scripts + ["punctuation", "numbers", "common_symbols"]))

        try:
            with tempfile.TemporaryDirectory(prefix=f"cproc_rust_{item_type}_{item_id}_") as temp_dir:
                temp_input_dir = os.path.join(temp_dir, 'input')
                temp_output_dir = os.path.join(temp_dir, 'output')
                temp_csv_path = os.path.join(temp_dir, 'analysis.csv')
                os.makedirs(temp_input_dir, exist_ok=True)
                os.makedirs(temp_output_dir, exist_ok=True)

                # Unique filename for the single item
                # The doc_id in generate_analysis_report_for_directory is based on filename.
                # Format: itemType_itemId_consultationId.md for uniqueness and traceability
                # However, the Rust code might expect simpler names if it parses IDs from them.
                # RustProcessor uses `doc_{doc_id}.md`. We'll use a similar simple one.
                # For pipeline, we are passing item_id, so make it `item_{item_id}.md`.
                temp_filename = f"item_{item_id}.md"
                temp_filepath = os.path.join(temp_input_dir, temp_filename)

                with open(temp_filepath, 'w', encoding='utf-8') as f:
                    f.write(text_content)
                
                self.logger.debug(f"Wrote content for {item_type} {item_id} to temp file {temp_filepath}")

                self.rust_text_cleaner.generate_analysis_report_for_directory(
                    temp_input_dir,
                    temp_csv_path,
                    temp_output_dir,
                    final_scripts_to_pass,
                    threads
                )

                if not os.path.exists(temp_csv_path):
                    self.logger.error(f"Rust cleaner did not produce analysis.csv for {item_type} {item_id} at {temp_csv_path}")
                    return default_return
                
                # Read the analysis CSV (should contain one row)
                if not self.pd:
                    self.logger.error("Pandas (self.pd) not available. Cannot read Rust analysis CSV.")
                    return default_return
                    
                df = self.pd.read_csv(temp_csv_path)
                if df.empty:
                    self.logger.error(f"Rust analysis.csv is empty for {item_type} {item_id}.")
                    return default_return

                row = df.iloc[0]
                csv_filename = row.get('File Name')

                # Ensure the row from CSV corresponds to our input file
                if csv_filename != temp_filename:
                    self.logger.error(f"Mismatch in CSV filename. Expected {temp_filename}, got {csv_filename} for {item_type} {item_id}")
                    return default_return
                
                cleaned_filepath = os.path.join(temp_output_dir, temp_filename)
                cleaned_text_content = "" # Default to empty if file not found
                if os.path.exists(cleaned_filepath):
                    with open(cleaned_filepath, 'r', encoding='utf-8') as f:
                        cleaned_text_content = f.read()
                else:
                    self.logger.warning(f"Cleaned file not found for {item_type} {item_id} at {cleaned_filepath}. Using empty string.")

                # Extract metrics, handling potential missing columns or non-numeric values
                badness_score_val = row.get('Badness Score')
                if badness_score_val is None: badness_score_val = row.get('Badness') # Fallback name
                
                try:
                    badness_score = float(badness_score_val) if badness_score_val is not None else 1.0
                except (ValueError, TypeError):
                    self.logger.warning(f"Could not parse badness score '{badness_score_val}'. Defaulting to 1.0 for {item_type} {item_id}")
                    badness_score = 1.0

                try:
                    greek_pct_str = str(row.get('Greek Percentage', '0')).replace('%', '')
                    greek_percentage = float(greek_pct_str) if greek_pct_str else 0.0
                except (ValueError, TypeError):
                    self.logger.warning(f"Could not parse Greek Percentage '{row.get('Greek Percentage')}'. Defaulting to 0.0 for {item_type} {item_id}")
                    greek_percentage = 0.0

                try:
                    # Assuming 'Latin Percentage' corresponds to English for this calculation
                    latin_pct_str = str(row.get('Latin Percentage', '0')).replace('%', '')
                    english_percentage = float(latin_pct_str) if latin_pct_str else 0.0
                except (ValueError, TypeError):
                    self.logger.warning(f"Could not parse Latin Percentage '{row.get('Latin Percentage')}'. Defaulting to 0.0 for {item_type} {item_id}")
                    english_percentage = 0.0
                
                self.logger.debug(f"Successfully cleaned {item_type} {item_id}. Score: {badness_score:.3f}, Greek: {greek_percentage:.2f}%, English: {english_percentage:.2f}%")
                return cleaned_text_content, badness_score, greek_percentage, english_percentage

        except Exception as e:
            self.logger.error(f"Error during Rust cleaning for {item_type} {item_id} (consultation {consultation_id}): {e}", exc_info=True)
            return default_return # Return original content and error scores 