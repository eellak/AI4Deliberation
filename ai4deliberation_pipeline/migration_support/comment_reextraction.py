#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Comment Re-extraction Script

Re-extracts all comments from their original sources using the current markdownify method.
This ensures all comments are properly extracted with the correct extraction method and
any improvements made to the comment extraction logic.
"""

import os
import sys
import sqlite3
import logging
from datetime import datetime
from typing import Dict, List, Optional
import time

# Add the project root to path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
sys.path.append(project_root)

# Import scraper components
try:
    from scraper.content_scraper import extract_comments, scrape_article_content
    from scraper.db_models import init_db, Article, Comment
    from scraper.utils import get_request_headers
    import requests
    from bs4 import BeautifulSoup
except ImportError as e:
    print(f"Warning: Could not import scraper components: {e}")
    print("Make sure you're running from the project root directory")
    sys.exit(1)

# Set up logging
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class CommentReextractor:
    """Handles re-extraction of comments from original sources."""
    
    def __init__(self, database_path: str):
        """
        Initialize the re-extractor.
        
        Args:
            database_path: Path to the database
        """
        self.database_path = database_path
        self.stats = {
            'articles_processed': 0,
            'comments_before': 0,
            'comments_after': 0,
            'comments_updated': 0,
            'comments_new': 0,
            'comments_removed': 0,
            'errors': 0,
            'articles_with_errors': []
        }
    
    def get_articles_for_reextraction(self) -> List[Dict]:
        """Get all articles that need comment re-extraction."""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        # Get all articles with their URLs
        cursor.execute("""
            SELECT a.id, a.url, a.title, 
                   (SELECT COUNT(*) FROM comments WHERE article_id = a.id) as comment_count
            FROM articles a
            ORDER BY a.id
        """)
        
        articles = []
        for row in cursor.fetchall():
            articles.append({
                'id': row[0],
                'url': row[1],
                'title': row[2],
                'current_comment_count': row[3]
            })
        
        conn.close()
        return articles
    
    def backup_comments(self, article_id: int) -> List[Dict]:
        """Create a backup of current comments for an article."""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, comment_id, username, date, content, extraction_method
            FROM comments 
            WHERE article_id = ?
        """, (article_id,))
        
        comments = []
        for row in cursor.fetchall():
            comments.append({
                'id': row[0],
                'comment_id': row[1],
                'username': row[2],
                'date': row[3],
                'content': row[4],
                'extraction_method': row[5]
            })
        
        conn.close()
        return comments
    
    def extract_comments_from_url(self, article_url: str) -> List[Dict]:
        """Extract comments from an article URL using the current scraper."""
        try:
            logger.info(f"Fetching comments from: {article_url}")
            
            # Fetch the page
            response = requests.get(article_url, headers=get_request_headers(), timeout=30, allow_redirects=True)
            response.raise_for_status()
            
            # Parse with BeautifulSoup
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Use the existing comment extraction logic
            comments = extract_comments(soup, article_url)
            
            # Mark all comments as extracted with markdownify
            for comment in comments:
                comment['extraction_method'] = 'markdownify'
            
            logger.info(f"Extracted {len(comments)} comments")
            return comments
            
        except Exception as e:
            logger.error(f"Error extracting comments from {article_url}: {e}")
            self.stats['errors'] += 1
            return []
    
    def update_article_comments(self, article_id: int, new_comments: List[Dict]) -> Dict[str, int]:
        """Update comments for an article."""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        # Get current comments
        current_comments = self.backup_comments(article_id)
        
        # Track changes
        changes = {
            'updated': 0,
            'new': 0,
            'removed': 0
        }
        
        # Delete all existing comments for this article
        cursor.execute("DELETE FROM comments WHERE article_id = ?", (article_id,))
        changes['removed'] = len(current_comments)
        
        # Insert new comments
        for comment in new_comments:
            cursor.execute("""
                INSERT INTO comments 
                (comment_id, username, date, content, extraction_method, article_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                comment['comment_id'],
                comment['username'],
                comment['date'],
                comment['content'],
                comment['extraction_method'],
                article_id
            ))
            changes['new'] += 1
        
        # Check which comments are actually new vs updated
        # This is approximate since we deleted and re-inserted
        new_comment_ids = set(c['comment_id'] for c in new_comments)
        old_comment_ids = set(c['comment_id'] for c in current_comments if c['comment_id'])
        
        truly_new = len(new_comment_ids - old_comment_ids)
        updated = len(new_comment_ids & old_comment_ids)
        
        changes['new'] = truly_new
        changes['updated'] = updated
        
        conn.commit()
        conn.close()
        
        return changes
    
    def reextract_article_comments(self, article: Dict) -> bool:
        """Re-extract comments for a single article."""
        try:
            logger.info(f"Re-extracting comments for article: {article['title']}")
            logger.info(f"Current comment count: {article['current_comment_count']}")
            
            # Extract new comments
            new_comments = self.extract_comments_from_url(article['url'])
            
            # Update the database
            changes = self.update_article_comments(article['id'], new_comments)
            
            # Update statistics
            self.stats['comments_before'] += article['current_comment_count']
            self.stats['comments_after'] += len(new_comments)
            self.stats['comments_updated'] += changes['updated']
            self.stats['comments_new'] += changes['new']
            self.stats['comments_removed'] += changes['removed'] - changes['updated'] - changes['new']
            
            logger.info(f"Updated comments: {changes['updated']}, New: {changes['new']}, Removed: {changes['removed']}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error re-extracting comments for article {article['id']}: {e}")
            self.stats['errors'] += 1
            self.stats['articles_with_errors'].append({
                'id': article['id'],
                'title': article['title'],
                'url': article['url'],
                'error': str(e)
            })
            return False
    
    def run_full_reextraction(self, limit: Optional[int] = None, delay: float = 0.5) -> bool:
        """Run complete comment re-extraction."""
        logger.info("Starting comment re-extraction process...")
        
        # Get articles to process
        articles = self.get_articles_for_reextraction()
        
        if limit:
            articles = articles[:limit]
            logger.info(f"Processing limited to first {limit} articles")
        
        logger.info(f"Found {len(articles)} articles to process")
        
        # If no limit specified and we have a lot of articles, recommend a smaller batch
        if not limit and len(articles) > 100:
            logger.warning(f"Found {len(articles)} articles to process - this could take hours!")
            logger.warning("Consider running with --limit option for testing, e.g. --limit 50")
            logger.warning("Or use smaller batches by running multiple times with different limits")
            
            # Ask for confirmation in interactive mode
            try:
                response = input(f"Continue with all {len(articles)} articles? (y/N): ")
                if response.lower() != 'y':
                    logger.info("Aborting re-extraction. Use --limit for smaller batches.")
                    return False
            except (EOFError, KeyboardInterrupt):
                logger.info("Aborting re-extraction.")
                return False
        
        # Process each article
        success_count = 0
        total_time = 0
        
        for i, article in enumerate(articles):
            start_time = time.time()
            logger.info(f"Processing article {i+1}/{len(articles)}: {article['title']}")
            
            # Add delay between requests to be respectful
            if i > 0:
                time.sleep(delay)
            
            if self.reextract_article_comments(article):
                success_count += 1
            
            self.stats['articles_processed'] += 1
            
            # Calculate and log progress every 10 articles
            elapsed = time.time() - start_time
            total_time += elapsed
            
            if (i + 1) % 10 == 0:
                avg_time = total_time / (i + 1)
                remaining = len(articles) - (i + 1)
                eta_minutes = (remaining * avg_time) / 60
                logger.info(f"Progress: {i+1}/{len(articles)} articles processed")
                logger.info(f"Average time per article: {avg_time:.2f}s, ETA: {eta_minutes:.1f} minutes")
        
        # Generate summary
        self.generate_reextraction_report()
        
        logger.info(f"Re-extraction complete. {success_count}/{len(articles)} articles processed successfully")
        
        return success_count == len(articles)
    
    def generate_reextraction_report(self) -> str:
        """Generate a detailed re-extraction report."""
        report = []
        report.append("Comment Re-extraction Report")
        report.append("=" * 50)
        report.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append(f"Database: {self.database_path}")
        report.append("")
        
        report.append("Processing Statistics:")
        report.append(f"  Articles processed: {self.stats['articles_processed']}")
        report.append(f"  Comments before: {self.stats['comments_before']}")
        report.append(f"  Comments after: {self.stats['comments_after']}")
        report.append(f"  Comments updated: {self.stats['comments_updated']}")
        report.append(f"  Comments new: {self.stats['comments_new']}")
        report.append(f"  Comments removed: {self.stats['comments_removed']}")
        report.append(f"  Net change: {self.stats['comments_after'] - self.stats['comments_before']}")
        report.append(f"  Errors: {self.stats['errors']}")
        report.append("")
        
        if self.stats['articles_with_errors']:
            report.append("Articles with Errors:")
            for error_info in self.stats['articles_with_errors'][:10]:  # Show first 10
                report.append(f"  - Article {error_info['id']}: {error_info['title']}")
                report.append(f"    URL: {error_info['url']}")
                report.append(f"    Error: {error_info['error']}")
                report.append("")
            
            if len(self.stats['articles_with_errors']) > 10:
                report.append(f"  ... and {len(self.stats['articles_with_errors']) - 10} more errors")
                report.append("")
        
        report.append("Re-extraction Results:")
        if self.stats['comments_after'] > self.stats['comments_before']:
            report.append(f"✓ Gained {self.stats['comments_after'] - self.stats['comments_before']} comments")
        elif self.stats['comments_after'] < self.stats['comments_before']:
            report.append(f"⚠ Lost {self.stats['comments_before'] - self.stats['comments_after']} comments")
        else:
            report.append("✓ Comment count unchanged")
        
        report.append("✓ All comments now use 'markdownify' extraction method")
        report.append("✓ Comments extracted with latest scraper improvements")
        report.append("")
        
        report.append("Notes:")
        report.append("- Some comment differences may be due to improved extraction logic")
        report.append("- All comments now consistently use markdownify method")
        report.append("- Comments may have better content formatting")
        report.append("- Lost comments may have been duplicates or extraction errors")
        
        report.append("=" * 50)
        
        # Save report to file
        report_text = "\n".join(report)
        report_path = f"{self.database_path}_comment_reextraction_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        
        try:
            with open(report_path, 'w', encoding='utf-8') as f:
                f.write(report_text)
            logger.info(f"Re-extraction report saved to: {report_path}")
        except Exception as e:
            logger.error(f"Error saving report: {e}")
        
        # Also log the summary
        logger.info("\nComment Re-extraction Summary:")
        logger.info("=" * 40)
        logger.info(f"Articles processed: {self.stats['articles_processed']}")
        logger.info(f"Comments before: {self.stats['comments_before']}")
        logger.info(f"Comments after: {self.stats['comments_after']}")
        logger.info(f"Net change: {self.stats['comments_after'] - self.stats['comments_before']}")
        logger.info(f"Errors: {self.stats['errors']}")
        logger.info("All comments now use 'markdownify' extraction method")
        logger.info("=" * 40)
        
        return report_text

def main():
    """Main function for command-line usage."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Re-extract all comments from original sources')
    parser.add_argument('database_path', help='Path to the database file')
    parser.add_argument('--limit', type=int, help='Limit number of articles to process')
    parser.add_argument('--delay', type=float, default=0.5, 
                       help='Delay between requests in seconds (default: 0.5)')
    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would be processed without making changes')
    
    args = parser.parse_args()
    
    # Resolve path
    database_path = os.path.abspath(args.database_path)
    
    if not os.path.exists(database_path):
        logger.error(f"Database not found: {database_path}")
        sys.exit(1)
    
    reextractor = CommentReextractor(database_path)
    
    if args.dry_run:
        logger.info("DRY RUN MODE - No changes will be made")
        articles = reextractor.get_articles_for_reextraction()
        if args.limit:
            articles = articles[:args.limit]
        
        logger.info(f"Would process {len(articles)} articles:")
        total_comments = 0
        for article in articles[:10]:  # Show first 10
            logger.info(f"  - {article['title']} ({article['current_comment_count']} comments)")
            total_comments += article['current_comment_count']
        
        if len(articles) > 10:
            remaining_comments = sum(a['current_comment_count'] for a in articles[10:])
            total_comments += remaining_comments
            logger.info(f"  ... and {len(articles) - 10} more articles")
        
        logger.info(f"Total comments to re-extract: {total_comments}")
        sys.exit(0)
    
    success = reextractor.run_full_reextraction(
        limit=args.limit,
        delay=args.delay
    )
    
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main() 