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
        """Setup the processing modules."""
        try:
            # Import Rust text cleaner
            import text_cleaner_rs
            self.rust_cleaner = text_cleaner_rs
            
            # Import markdownify for HTML processing
            import markdownify
            self.markdownify = markdownify
            
        except ImportError as e:
            self.logger.error(f"Failed to import required modules: {e}")
            raise
    
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
        try:
            # Import GlossAPI Corpus
            try:
                from glossapi.corpus import Corpus
            except ImportError:
                self.logger.warning("GlossAPI not found, trying custom path...")
                glossapi_path = "/mnt/data/glossapi"
                if os.path.exists(glossapi_path):
                    sys.path.append(glossapi_path)
                    from glossapi.corpus import Corpus
                else:
                    self.logger.error("GlossAPI not available for PDF extraction")
                    return None
            
            # Create temporary workspace for this PDF
            with tempfile.TemporaryDirectory(prefix='pdf_extraction_') as temp_workspace:
                # Create a simple DataFrame with just this PDF
                import pandas as pd
                
                pdf_df = pd.DataFrame({
                    'document_id': [1],
                    'redirected_url': [f'file://{pdf_path}']
                })
                
                # Save to parquet for GlossAPI
                parquet_path = os.path.join(temp_workspace, 'documents.parquet')
                pdf_df.to_parquet(parquet_path, index=False)
                
                # Create GlossAPI Corpus
                corpus = Corpus(
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
                self.rust_cleaner.generate_analysis_report_for_directory(
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