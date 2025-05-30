#!/usr/bin/env python3

import sqlite3
import sys
import os
from markdownify import markdownify as md
import logging
from typing import Optional, List, Tuple

# Add master_pipeline to path for config imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'master_pipeline'))
from utils import load_config, setup_logging

class HTMLProcessor:
    """HTML processing pipeline that converts HTML content to markdown using markdownify."""
    
    def __init__(self, config: dict):
        """Initialize the HTML processor with configuration."""
        self.config = config
        self.db_path = config['database']['default_path']
        self.batch_size = config['html_processing']['batch_size']
        self.markdownify_config = config['html_processing']['markdownify']
        
        # Setup logging
        self.logger = logging.getLogger(__name__)
        
    def get_unprocessed_articles(self) -> List[Tuple[int, str]]:
        """Get articles that need HTML content processing."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Get articles without content or with empty content
            cursor.execute("""
                SELECT id, raw_html 
                FROM articles 
                WHERE (content IS NULL OR content = '') 
                AND raw_html IS NOT NULL 
                AND raw_html != ''
                ORDER BY id
            """)
            
            articles = cursor.fetchall()
            conn.close()
            
            self.logger.info(f"Found {len(articles)} articles needing HTML processing")
            return articles
            
        except sqlite3.Error as e:
            self.logger.error(f"Database error getting unprocessed articles: {e}")
            return []
            
    def process_html_to_markdown(self, html_content: str) -> Optional[str]:
        """Convert HTML content to markdown using markdownify."""
        try:
            if not html_content or html_content.strip() == '':
                return None
                
            # Use markdownify with our configured settings
            markdown_text = md(
                html_content,
                heading_style=self.markdownify_config['heading_style'],
                bullets=self.markdownify_config['bullets'],
                strip=self.markdownify_config.get('convert_truefalse', ['b', 'strong', 'i', 'em']),
                wrap=self.markdownify_config.get('wrap', False),
                wrap_width=self.markdownify_config.get('wrap_width', 80)
            )
            
            # Clean up excessive whitespace
            if markdown_text:
                # Remove excessive newlines (more than 2 consecutive)
                import re
                markdown_text = re.sub(r'\n{3,}', '\n\n', markdown_text)
                markdown_text = markdown_text.strip()
                
            return markdown_text
            
        except Exception as e:
            self.logger.error(f"Error converting HTML to markdown: {e}")
            return None
            
    def update_article_content(self, article_id: int, content: str) -> bool:
        """Update an article's content and extraction method in the database."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Check if extraction_method column exists, add if not
            cursor.execute("PRAGMA table_info(articles)")
            columns = [column[1] for column in cursor.fetchall()]
            if 'extraction_method' not in columns:
                self.logger.info("Adding 'extraction_method' column to 'articles' table")
                cursor.execute("ALTER TABLE articles ADD COLUMN extraction_method TEXT")
                conn.commit()
            
            # Update the article
            cursor.execute("""
                UPDATE articles 
                SET content = ?, extraction_method = ? 
                WHERE id = ?
            """, (content, 'markdownify_pipeline', article_id))
            
            conn.commit()
            conn.close()
            return True
            
        except sqlite3.Error as e:
            self.logger.error(f"Database error updating article {article_id}: {e}")
            return False
            
    def process_articles_batch(self, articles: List[Tuple[int, str]]) -> Tuple[int, int]:
        """Process a batch of articles and return (success_count, error_count)."""
        success_count = 0
        error_count = 0
        
        for article_id, raw_html in articles:
            try:
                # Convert HTML to markdown
                markdown_content = self.process_html_to_markdown(raw_html)
                
                if markdown_content:
                    # Update database
                    if self.update_article_content(article_id, markdown_content):
                        success_count += 1
                        self.logger.debug(f"Successfully processed article {article_id}")
                    else:
                        error_count += 1
                        self.logger.warning(f"Failed to update article {article_id} in database")
                else:
                    error_count += 1
                    self.logger.warning(f"Failed to convert HTML for article {article_id}")
                    
            except Exception as e:
                error_count += 1
                self.logger.error(f"Error processing article {article_id}: {e}")
                
        return success_count, error_count
        
    def run_html_processing(self) -> bool:
        """Run the complete HTML processing pipeline."""
        self.logger.info("Starting HTML processing pipeline")
        
        # Get all unprocessed articles
        articles = self.get_unprocessed_articles()
        
        if not articles:
            self.logger.info("No articles need HTML processing")
            return True
            
        total_articles = len(articles)
        total_processed = 0
        total_errors = 0
        
        # Process articles in batches
        for i in range(0, total_articles, self.batch_size):
            batch = articles[i:i + self.batch_size]
            batch_num = (i // self.batch_size) + 1
            total_batches = (total_articles + self.batch_size - 1) // self.batch_size
            
            self.logger.info(f"Processing batch {batch_num}/{total_batches} ({len(batch)} articles)")
            
            success_count, error_count = self.process_articles_batch(batch)
            total_processed += success_count
            total_errors += error_count
            
            if batch_num % 5 == 0 or batch_num == total_batches:
                self.logger.info(
                    f"Progress: {total_processed}/{total_articles} processed, "
                    f"{total_errors} errors"
                )
        
        # Final summary
        self.logger.info(
            f"HTML processing completed: {total_processed}/{total_articles} articles processed, "
            f"{total_errors} errors"
        )
        
        return total_errors == 0

def run_html_pipeline(config: dict) -> bool:
    """Main entry point for HTML processing pipeline."""
    processor = HTMLProcessor(config)
    return processor.run_html_processing()

if __name__ == "__main__":
    # Load configuration and setup logging
    config = load_config()
    setup_logging(config)
    
    logger = logging.getLogger(__name__)
    logger.info("Starting HTML processing pipeline")
    
    try:
        success = run_html_pipeline(config)
        if success:
            logger.info("HTML processing pipeline completed successfully")
        else:
            logger.error("HTML processing pipeline completed with errors")
            sys.exit(1)
    except Exception as e:
        logger.error(f"HTML processing pipeline failed: {e}")
        sys.exit(1) 