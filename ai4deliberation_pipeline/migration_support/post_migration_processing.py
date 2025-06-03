#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Post-Migration Processing Script

Handles processing tasks needed after data transfer migration:
1. Rust cleaning for documents with content
2. Populating extraction methods based on content analysis
3. Verifying data integrity and processing results
"""

import os
import sys
import sqlite3
import logging
from datetime import datetime
from typing import Dict, List, Optional

# Add the project root to path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
sys.path.append(project_root)

# Import pipeline components
try:
    from rust_processor.rust_processor import RustProcessor
except ImportError as e:
    print(f"Warning: Could not import RustProcessor: {e}")
    RustProcessor = None

# Set up logging
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class PostMigrationProcessor:
    """Handles post-migration processing tasks."""
    
    def __init__(self, database_path: str):
        """
        Initialize the processor.
        
        Args:
            database_path: Path to the migrated database
        """
        self.database_path = database_path
        self.stats = {
            'documents_processed': 0,
            'documents_cleaned': 0,
            'articles_processed': 0,
            'extraction_methods_updated': 0,
            'errors': 0
        }
    
    def get_processing_stats(self) -> Dict[str, int]:
        """Get current processing statistics."""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        stats = {}
        
        # Documents with content
        cursor.execute("SELECT COUNT(*) FROM documents WHERE content IS NOT NULL AND content != ''")
        stats['documents_with_content'] = cursor.fetchone()[0]
        
        # Documents already cleaned
        cursor.execute("SELECT COUNT(*) FROM documents WHERE content_cleaned IS NOT NULL")
        stats['documents_cleaned'] = cursor.fetchone()[0]
        
        # Documents needing cleaning
        cursor.execute("""
            SELECT COUNT(*) FROM documents 
            WHERE content IS NOT NULL AND content != '' 
            AND content_cleaned IS NULL
        """)
        stats['documents_need_cleaning'] = cursor.fetchone()[0]
        
        # Articles with content
        cursor.execute("SELECT COUNT(*) FROM articles WHERE content IS NOT NULL AND content != ''")
        stats['articles_with_content'] = cursor.fetchone()[0]
        
        # Articles already cleaned
        cursor.execute("SELECT COUNT(*) FROM articles WHERE content_cleaned IS NOT NULL")
        stats['articles_cleaned'] = cursor.fetchone()[0]
        
        # Extraction methods
        cursor.execute("SELECT extraction_method, COUNT(*) FROM documents GROUP BY extraction_method")
        extraction_methods = dict(cursor.fetchall())
        stats['extraction_methods'] = extraction_methods
        
        conn.close()
        return stats
    
    def print_current_status(self):
        """Print current processing status."""
        stats = self.get_processing_stats()
        
        logger.info("\nCurrent Processing Status:")
        logger.info("=" * 50)
        logger.info(f"Documents with content: {stats['documents_with_content']}")
        logger.info(f"Documents cleaned: {stats['documents_cleaned']}")
        logger.info(f"Documents needing cleaning: {stats['documents_need_cleaning']}")
        logger.info(f"Articles with content: {stats['articles_with_content']}")
        logger.info(f"Articles cleaned: {stats['articles_cleaned']}")
        
        logger.info("\nExtraction Methods:")
        for method, count in stats.get('extraction_methods', {}).items():
            logger.info(f"  {method}: {count}")
        
        logger.info("=" * 50)
    
    def run_rust_cleaning(self) -> bool:
        """Run Rust cleaning on documents with content."""
        if RustProcessor is None:
            logger.error("RustProcessor not available. Cannot run Rust cleaning.")
            return False
        
        logger.info("Starting Rust cleaning process...")
        
        try:
            # Initialize Rust processor
            processor = RustProcessor(db_path_override=self.database_path)
            
            # Get documents needing cleaning
            documents = processor.get_documents_needing_cleaning()
            logger.info(f"Found {len(documents)} documents needing cleaning")
            
            if not documents:
                logger.info("No documents need cleaning")
                return True
            
            # Process documents with Rust
            results = processor.process_documents_with_rust(documents)
            
            if results:
                # Update database with results
                success = processor.update_database_with_results(results)
                
                if success:
                    self.stats['documents_processed'] = len(documents)
                    self.stats['documents_cleaned'] = len(results)
                    logger.info(f"Successfully cleaned {len(results)} documents")
                    return True
                else:
                    logger.error("Failed to update database with Rust cleaning results")
                    return False
            else:
                logger.error("Rust cleaning failed to produce results")
                return False
                
        except Exception as e:
            logger.error(f"Error during Rust cleaning: {e}")
            import traceback
            traceback.print_exc()
            self.stats['errors'] += 1
            return False
    
    def update_extraction_methods(self) -> bool:
        """Update extraction methods based on content analysis."""
        logger.info("Updating extraction methods...")
        
        try:
            conn = sqlite3.connect(self.database_path)
            cursor = conn.cursor()
            
            # Check extraction method distribution
            cursor.execute("SELECT extraction_method, COUNT(*) FROM documents GROUP BY extraction_method")
            doc_methods = dict(cursor.fetchall())
            logger.info(f"Document extraction methods: {doc_methods}")
            
            cursor.execute("SELECT extraction_method, COUNT(*) FROM articles GROUP BY extraction_method")
            article_methods = dict(cursor.fetchall())
            logger.info(f"Article extraction methods: {article_methods}")
            
            cursor.execute("SELECT extraction_method, COUNT(*) FROM comments GROUP BY extraction_method")
            comment_methods = dict(cursor.fetchall())
            logger.info(f"Comment extraction methods: {comment_methods}")
            
            # Since migration now sets correct extraction methods, we mainly verify consistency
            updated_count = 0
            
            # Fix any NULL extraction methods that might exist
            cursor.execute("UPDATE documents SET extraction_method = 'docling' WHERE extraction_method IS NULL")
            updated_count += cursor.rowcount
            
            cursor.execute("UPDATE articles SET extraction_method = 'markdownify' WHERE extraction_method IS NULL")
            updated_count += cursor.rowcount
            
            cursor.execute("UPDATE comments SET extraction_method = 'markdownify' WHERE extraction_method IS NULL")
            updated_count += cursor.rowcount
            
            # Check for comments that might need re-extraction
            cursor.execute("""
                SELECT COUNT(*) FROM comments 
                WHERE content LIKE '%docling%' OR content LIKE '%pdf%' OR content LIKE '%extraction%'
            """)
            potentially_docling_comments = cursor.fetchone()[0]
            
            if potentially_docling_comments > 0:
                logger.warning(f"Found {potentially_docling_comments} comments that might have been extracted with docling")
                logger.warning("Consider reviewing these comments for re-extraction")
            
            conn.commit()
            conn.close()
            
            self.stats['extraction_methods_updated'] = updated_count
            logger.info(f"Updated extraction method for {updated_count} records")
            
            if potentially_docling_comments > 0:
                logger.info("Migration note: Some comments may need re-extraction from original sources")
            
            return True
            
        except Exception as e:
            logger.error(f"Error updating extraction methods: {e}")
            self.stats['errors'] += 1
            return False
    
    def verify_processing_results(self) -> bool:
        """Verify that processing was successful."""
        logger.info("Verifying processing results...")
        
        try:
            stats = self.get_processing_stats()
            
            # Check if all documents with content have been processed
            docs_with_content = stats['documents_with_content']
            docs_cleaned = stats['documents_cleaned']
            
            if docs_cleaned == docs_with_content:
                logger.info("✓ All documents with content have been cleaned")
                success = True
            else:
                logger.warning(f"✗ {docs_with_content - docs_cleaned} documents still need cleaning")
                success = False
            
            # Check extraction methods consistency
            extraction_methods = stats.get('extraction_methods', {})
            
            # Verify documents use docling
            docling_docs = extraction_methods.get('docling', 0)
            total_docs = sum(extraction_methods.values()) if extraction_methods else 0
            
            if total_docs > 0:
                docling_percentage = (docling_docs / total_docs) * 100
                logger.info(f"Documents using docling: {docling_docs}/{total_docs} ({docling_percentage:.1f}%)")
                
                if docling_percentage < 95:  # Allow some tolerance
                    logger.warning("Not all documents are using docling extraction method")
                    success = False
                else:
                    logger.info("✓ Documents correctly use docling extraction method")
            
            # Check for quality scores
            conn = sqlite3.connect(self.database_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT COUNT(*) FROM documents 
                WHERE content IS NOT NULL AND content != ''
                AND badness_score IS NOT NULL
            """)
            docs_with_scores = cursor.fetchone()[0]
            
            if docs_with_scores == docs_with_content:
                logger.info("✓ All documents have quality scores")
            else:
                logger.warning(f"✗ {docs_with_content - docs_with_scores} documents missing quality scores")
                success = False
            
            # Check external tables exist
            external_tables = ['nomoi', 'ypourgikes_apofaseis', 'proedrika_diatagmata', 'eu_regulations', 'eu_directives']
            for table_name in external_tables:
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                    count = cursor.fetchone()[0]
                    logger.info(f"✓ External table '{table_name}' exists with {count} records")
                except sqlite3.OperationalError:
                    logger.error(f"✗ External table '{table_name}' missing!")
                    success = False
            
            conn.close()
            return success
            
        except Exception as e:
            logger.error(f"Error verifying results: {e}")
            return False
    
    def generate_processing_report(self) -> str:
        """Generate a detailed processing report."""
        stats = self.get_processing_stats()
        
        report = []
        report.append("Post-Migration Processing Report")
        report.append("=" * 50)
        report.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append(f"Database: {self.database_path}")
        report.append("")
        
        report.append("Processing Statistics:")
        report.append(f"  Documents with content: {stats['documents_with_content']}")
        report.append(f"  Documents cleaned: {stats['documents_cleaned']}")
        report.append(f"  Documents needing cleaning: {stats['documents_need_cleaning']}")
        report.append(f"  Articles with content: {stats['articles_with_content']}")
        report.append(f"  Articles cleaned: {stats['articles_cleaned']}")
        report.append("")
        
        report.append("Extraction Methods:")
        for method, count in stats.get('extraction_methods', {}).items():
            report.append(f"  {method}: {count}")
        report.append("")
        
        # Check extraction method compliance
        try:
            conn = sqlite3.connect(self.database_path)
            cursor = conn.cursor()
            
            # Article extraction methods
            cursor.execute("SELECT extraction_method, COUNT(*) FROM articles GROUP BY extraction_method")
            article_methods = dict(cursor.fetchall())
            report.append("Article Extraction Methods:")
            for method, count in article_methods.items():
                report.append(f"  {method}: {count}")
            
            # Comment extraction methods
            cursor.execute("SELECT extraction_method, COUNT(*) FROM comments GROUP BY extraction_method")
            comment_methods = dict(cursor.fetchall())
            report.append("Comment Extraction Methods:")
            for method, count in comment_methods.items():
                report.append(f"  {method}: {count}")
            
            # External tables status
            external_tables = ['nomoi', 'ypourgikes_apofaseis', 'proedrika_diatagmata', 'eu_regulations', 'eu_directives']
            report.append("External Document Tables:")
            for table_name in external_tables:
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                    count = cursor.fetchone()[0]
                    report.append(f"  {table_name}: {count} records")
                except sqlite3.OperationalError:
                    report.append(f"  {table_name}: TABLE MISSING!")
            
            conn.close()
            
        except Exception as e:
            report.append(f"Error analyzing extraction methods: {e}")
        
        report.append("")
        
        report.append("Processing Session Statistics:")
        report.append(f"  Documents processed: {self.stats['documents_processed']}")
        report.append(f"  Documents cleaned: {self.stats['documents_cleaned']}")
        report.append(f"  Extraction methods updated: {self.stats['extraction_methods_updated']}")
        report.append(f"  Errors encountered: {self.stats['errors']}")
        report.append("")
        
        # Quality analysis
        try:
            conn = sqlite3.connect(self.database_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT AVG(badness_score), MIN(badness_score), MAX(badness_score)
                FROM documents WHERE badness_score IS NOT NULL
            """)
            row = cursor.fetchone()
            if row and row[0] is not None:
                report.append("Quality Scores:")
                report.append(f"  Average badness: {row[0]:.4f}")
                report.append(f"  Best score: {row[1]:.4f}")
                report.append(f"  Worst score: {row[2]:.4f}")
                report.append("")
            
            cursor.execute("""
                SELECT AVG(greek_percentage), AVG(english_percentage)
                FROM documents WHERE greek_percentage IS NOT NULL
            """)
            row = cursor.fetchone()
            if row and row[0] is not None:
                report.append("Language Analysis:")
                report.append(f"  Average Greek content: {row[0]:.1f}%")
                report.append(f"  Average English content: {row[1]:.1f}%")
                report.append("")
            
            conn.close()
            
        except Exception as e:
            report.append(f"Error generating quality analysis: {e}")
            report.append("")
        
        report.append("Migration Notes:")
        report.append("- All documents set to use 'docling' extraction method")
        report.append("- All articles set to use 'markdownify' extraction method") 
        report.append("- All comments set to use 'markdownify' extraction method")
        report.append("- Comments may need re-extraction if originally from docling")
        report.append("- 5 external document tables created (nomoi, etc.)")
        report.append("")
        
        report.append("Recommended Next Steps:")
        report.append("1. Run scraper to fetch new data: python scraper/main_scraper.py --update")
        report.append("2. Review comments for potential re-extraction needs")
        report.append("3. Populate external document tables as needed")
        report.append("4. Test full pipeline functionality")
        
        report.append("=" * 50)
        
        return "\n".join(report)
    
    def run_full_processing(self) -> bool:
        """Run the complete post-migration processing."""
        logger.info("Starting post-migration processing...")
        
        # Step 1: Print current status
        self.print_current_status()
        
        # Step 2: Run Rust cleaning
        logger.info("\nStep 1: Running Rust cleaning...")
        rust_success = self.run_rust_cleaning()
        
        if not rust_success:
            logger.error("Rust cleaning failed. Continuing with other processing...")
        
        # Step 3: Update extraction methods
        logger.info("\nStep 2: Updating extraction methods...")
        methods_success = self.update_extraction_methods()
        
        # Step 4: Verify results
        logger.info("\nStep 3: Verifying processing results...")
        verification_success = self.verify_processing_results()
        
        # Step 5: Generate report
        logger.info("\nStep 4: Generating processing report...")
        report = self.generate_processing_report()
        
        # Save report to file
        report_path = f"{self.database_path}_processing_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report)
        
        logger.info(f"Processing report saved to: {report_path}")
        
        # Print summary
        logger.info("\nPost-Migration Processing Summary:")
        logger.info("=" * 50)
        logger.info(f"Rust cleaning: {'✓' if rust_success else '✗'}")
        logger.info(f"Extraction methods: {'✓' if methods_success else '✗'}")
        logger.info(f"Verification: {'✓' if verification_success else '✗'}")
        logger.info(f"Report generated: ✓")
        
        overall_success = rust_success and methods_success and verification_success
        logger.info(f"Overall success: {'✓' if overall_success else '✗'}")
        logger.info("=" * 50)
        
        return overall_success

def main():
    """Main function for command-line usage."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Run post-migration processing tasks')
    parser.add_argument('database_path', help='Path to the migrated database file')
    parser.add_argument('--rust-only', action='store_true',
                       help='Only run Rust cleaning')
    parser.add_argument('--methods-only', action='store_true',
                       help='Only update extraction methods')
    parser.add_argument('--verify-only', action='store_true',
                       help='Only verify processing results')
    parser.add_argument('--status-only', action='store_true',
                       help='Only show current status')
    
    args = parser.parse_args()
    
    # Resolve path
    database_path = os.path.abspath(args.database_path)
    
    if not os.path.exists(database_path):
        logger.error(f"Database not found: {database_path}")
        sys.exit(1)
    
    processor = PostMigrationProcessor(database_path)
    
    if args.status_only:
        processor.print_current_status()
        sys.exit(0)
    elif args.rust_only:
        success = processor.run_rust_cleaning()
    elif args.methods_only:
        success = processor.update_extraction_methods()
    elif args.verify_only:
        success = processor.verify_processing_results()
    else:
        success = processor.run_full_processing()
    
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main() 