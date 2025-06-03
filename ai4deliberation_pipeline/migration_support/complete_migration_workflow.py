#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Complete Migration Workflow
This script orchestrates the entire migration process including:
1. Data transfer from old to new database
2. Post-migration processing (Rust cleaning)
3. Running scraper to verify migration and fetch new data
4. Comprehensive verification and reporting

Usage:
    python migration_support/complete_migration_workflow.py
    python migration_support/complete_migration_workflow.py --dry-run
    python migration_support/complete_migration_workflow.py --skip-processing
    python migration_support/complete_migration_workflow.py --skip-scraper
"""

import argparse
import logging
import sys
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent))

from migration_support.data_transfer_migration import DataTransferMigration
from migration_support.post_migration_processing import PostMigrationProcessor
from migration_support.comment_reextraction import CommentReextractor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('migration_workflow.log')
    ]
)
logger = logging.getLogger(__name__)

class CompleteMigrationWorkflow:
    """Orchestrates the complete migration workflow."""
    
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.downloaded_db_name = "deliberation_data_gr_markdownify_DOWNLOADED.db"
        self.migrated_db_name = f"deliberation_data_gr_MIGRATED_FRESH_{datetime.now().strftime('%Y%m%d%H%M%S')}.db"
        
        self.old_db_path = self.downloaded_db_name # Source for migration will be the freshly downloaded DB
        self.new_db_path = self.migrated_db_name   # Target for all operations in this workflow run

        self.start_time = datetime.now()
        self.workflow_stats = {
            'migration_success': False,
            'processing_success': False,
            'reextraction_success': False,
            'scraper_success': False,
            'total_time': 0,
            'phase_times': {}
        }
    
    def run_migration_phase(self) -> bool:
        """Run the data transfer migration phase."""
        logger.info("=" * 60)
        logger.info("PHASE 1: DATA TRANSFER MIGRATION")
        logger.info("=" * 60)
        
        phase_start = time.time()
        
        if self.dry_run:
            logger.info("[DRY RUN] Would transfer data from old to new database")
            logger.info(f"[DRY RUN] Source: {self.old_db_path}")
            logger.info(f"[DRY RUN] Target: {self.new_db_path}")
            self.workflow_stats['migration_success'] = True
        else:
            migrator = DataTransferMigration(self.old_db_path, self.new_db_path)
            success = migrator.run_migration()
            self.workflow_stats['migration_success'] = success
            
            if not success:
                logger.error("Migration failed! Stopping workflow.")
                return False
        
        phase_time = time.time() - phase_start
        self.workflow_stats['phase_times']['migration'] = phase_time
        logger.info(f"Phase 1 completed in {phase_time:.2f} seconds")
        return True
    
    def run_processing_phase(self) -> bool:
        """Run the post-migration processing phase."""
        logger.info("=" * 60)
        logger.info("PHASE 2: POST-MIGRATION PROCESSING")
        logger.info("=" * 60)
        
        phase_start = time.time()
        
        if self.dry_run:
            logger.info("[DRY RUN] Would run Rust cleaning on documents with content")
            logger.info("[DRY RUN] Would populate quality scores and language percentages")
            self.workflow_stats['processing_success'] = True
        else:
            processor = PostMigrationProcessor(self.new_db_path)
            success = processor.run_full_processing()
            self.workflow_stats['processing_success'] = success
            
            if not success:
                logger.warning("Post-processing had issues but continuing with workflow")
        
        phase_time = time.time() - phase_start
        self.workflow_stats['phase_times']['processing'] = phase_time
        logger.info(f"Phase 2 completed in {phase_time:.2f} seconds")
        return True
    
    def run_reextraction_phase(self) -> bool:
        """Run the comment re-extraction phase."""
        logger.info("=" * 60)
        logger.info("PHASE 2.5: COMMENT RE-EXTRACTION")
        logger.info("=" * 60)
        
        phase_start = time.time()
        
        if self.dry_run:
            logger.info("[DRY RUN] Would re-extract all comments from original sources")
            logger.info("[DRY RUN] Would mark all comments as extracted with 'markdownify'")
            self.workflow_stats['reextraction_success'] = True
        else:
            reextractor = CommentReextractor(self.new_db_path)
            success = reextractor.run_full_reextraction()
            self.workflow_stats['reextraction_success'] = success
            
            if not success:
                logger.warning("Comment re-extraction had issues but continuing with workflow")
        
        phase_time = time.time() - phase_start
        self.workflow_stats['phase_times']['reextraction'] = phase_time
        logger.info(f"Phase 2.5 completed in {phase_time:.2f} seconds")
        return True
    
    def run_scraper_phase(self) -> bool:
        """Run the scraper to verify migration and fetch new data."""
        logger.info("=" * 60)
        logger.info("PHASE 3: SCRAPER VERIFICATION")
        logger.info("=" * 60)
        
        phase_start = time.time()
        
        if self.dry_run:
            logger.info("[DRY RUN] Would run scraper to fetch new data and verify migration")
            self.workflow_stats['scraper_success'] = True
        else:
            # Check if scraper exists
            scraper_path = Path("scraper/main_scraper.py")
            if not scraper_path.exists():
                logger.warning("Scraper not found. Checking alternative locations...")
                possible_paths = [
                    "scraper/scraper.py",
                    "main_scraper.py",
                    "scraper.py"
                ]
                scraper_path = None
                for path in possible_paths:
                    if Path(path).exists():
                        scraper_path = Path(path)
                        break
                
                if not scraper_path:
                    logger.error("Scraper script not found! Please check scraper location.")
                    logger.info("Skipping scraper phase...")
                    self.workflow_stats['scraper_success'] = False
                    phase_time = time.time() - phase_start
                    self.workflow_stats['phase_times']['scraper'] = phase_time
                    return False
            
            logger.info(f"Running scraper: {scraper_path}")
            
            try:
                # Run scraper with update flag
                result = subprocess.run([
                    sys.executable, str(scraper_path), "--update"
                ], capture_output=True, text=True, timeout=1800)  # 30 minute timeout
                
                if result.returncode == 0:
                    logger.info("✓ Scraper completed successfully")
                    logger.info("Scraper output:")
                    for line in result.stdout.split('\n')[-10:]:  # Last 10 lines
                        if line.strip():
                            logger.info(f"  {line}")
                    self.workflow_stats['scraper_success'] = True
                else:
                    logger.error("✗ Scraper failed")
                    logger.error("Scraper error output:")
                    for line in result.stderr.split('\n')[-5:]:  # Last 5 error lines
                        if line.strip():
                            logger.error(f"  {line}")
                    self.workflow_stats['scraper_success'] = False
                    
            except subprocess.TimeoutExpired:
                logger.error("Scraper timed out after 30 minutes")
                self.workflow_stats['scraper_success'] = False
            except Exception as e:
                logger.error(f"Error running scraper: {e}")
                self.workflow_stats['scraper_success'] = False
        
        phase_time = time.time() - phase_start
        self.workflow_stats['phase_times']['scraper'] = phase_time
        logger.info(f"Phase 3 completed in {phase_time:.2f} seconds")
        return self.workflow_stats['scraper_success']
    
    def _download_fresh_db(self) -> bool:
        """Downloads the latest database from Hugging Face."""
        logger.info("=" * 60)
        logger.info("PHASE 0: DOWNLOADING FRESH DATABASE")
        logger.info("=" * 60)
        
        hf_url = "https://huggingface.co/datasets/glossAPI/opengov.gr-diaboyleuseis/resolve/main/deliberation_data_gr_markdownify.db"
        download_target_path = Path(self.downloaded_db_name)

        # Remove if it exists from a previous failed run to ensure freshness
        if download_target_path.exists():
            try:
                os.remove(download_target_path)
                logger.info(f"Removed existing downloaded DB: {download_target_path}")
            except OSError as e:
                logger.error(f"Error removing existing DB {download_target_path}: {e}")
                return False
        
        logger.info(f"Downloading database from {hf_url} to {download_target_path}...")
        
        if self.dry_run:
            logger.info(f"[DRY RUN] Would download DB to {download_target_path}")
            return True
            
        try:
            # Using curl for robust download, especially for large files and following redirects
            command = [
                "curl", "-L", # Follow redirects
                "-o", str(download_target_path), # Output file
                hf_url
            ]
            result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=600) # 10 min timeout
            logger.info("✓ Database downloaded successfully.")
            logger.debug(f"Curl output: {result.stdout}")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"✗ Error downloading database using curl. Return code: {e.returncode}")
            logger.error(f"Curl stderr: {e.stderr}")
            return False
        except subprocess.TimeoutExpired:
            logger.error("✗ Database download timed out after 10 minutes.")
            return False
        except Exception as e:
            logger.error(f"✗ An unexpected error occurred during database download: {e}")
            return False
    
    def verify_final_state(self) -> bool:
        """Perform final verification of the migration."""
        logger.info("=" * 60)
        logger.info("FINAL VERIFICATION")
        logger.info("=" * 60)
        
        if self.dry_run:
            logger.info("[DRY RUN] Would verify final database state")
            return True
        
        # Import here to avoid circular imports
        import sqlite3
        
        try:
            conn = sqlite3.connect(self.new_db_path)
            cursor = conn.cursor()
            
            # Check table existence and record counts
            tables = ['ministries', 'consultations', 'articles', 'documents', 'comments']
            external_tables = ['nomoi', 'ypourgikes_apofaseis', 'proedrika_diatagmata', 'eu_regulations', 'eu_directives']
            
            all_good = True
            total_records = 0
            
            logger.info("Core Tables:")
            for table in tables:
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM {table}")
                    count = cursor.fetchone()[0]
                    total_records += count
                    logger.info(f"  ✓ {table}: {count:,} records")
                except sqlite3.OperationalError as e:
                    logger.error(f"  ✗ {table}: {e}")
                    all_good = False
            
            logger.info("External Document Tables:")
            for table in external_tables:
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM {table}")
                    count = cursor.fetchone()[0]
                    logger.info(f"  ✓ {table}: {count} records")
                except sqlite3.OperationalError as e:
                    logger.error(f"  ✗ {table}: {e}")
                    all_good = False
            
            # Check extraction methods
            logger.info("Extraction Method Compliance:")
            
            cursor.execute("SELECT extraction_method, COUNT(*) FROM documents GROUP BY extraction_method")
            doc_methods = dict(cursor.fetchall())
            for method, count in doc_methods.items():
                check = "✓" if method == "docling" else "⚠"
                logger.info(f"  {check} Documents - {method}: {count}")
            
            cursor.execute("SELECT extraction_method, COUNT(*) FROM articles GROUP BY extraction_method")
            article_methods = dict(cursor.fetchall())
            for method, count in article_methods.items():
                check = "✓" if method == "markdownify" else "⚠"
                logger.info(f"  {check} Articles - {method}: {count}")
            
            cursor.execute("SELECT extraction_method, COUNT(*) FROM comments GROUP BY extraction_method")
            comment_methods = dict(cursor.fetchall())
            for method, count in comment_methods.items():
                check = "✓" if method == "markdownify" else "⚠"
                logger.info(f"  {check} Comments - {method}: {count}")
            
            # Check processed content
            cursor.execute("""
                SELECT COUNT(*) FROM documents 
                WHERE content IS NOT NULL AND content != '' AND content_cleaned IS NOT NULL
            """)
            cleaned_docs = cursor.fetchone()[0]
            
            cursor.execute("""
                SELECT COUNT(*) FROM documents 
                WHERE content IS NOT NULL AND content != ''
            """)
            total_docs_with_content = cursor.fetchone()[0]
            
            logger.info(f"Content Processing: {cleaned_docs}/{total_docs_with_content} documents cleaned")
            
            conn.close()
            
            logger.info(f"Total migrated records: {total_records:,}")
            
            return all_good
            
        except Exception as e:
            logger.error(f"Error in final verification: {e}")
            return False
    
    def generate_final_report(self):
        """Generate the final workflow report."""
        total_time = time.time() - self.start_time.timestamp()
        self.workflow_stats['total_time'] = total_time
        
        logger.info("=" * 60)
        logger.info("MIGRATION WORKFLOW COMPLETED")
        logger.info("=" * 60)
        
        logger.info("Workflow Summary:")
        logger.info(f"  Start time: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"  Total duration: {total_time:.2f} seconds ({total_time/60:.1f} minutes)")
        logger.info(f"  Dry run mode: {self.dry_run}")
        
        logger.info("Phase Results:")
        phase_1 = "✓" if self.workflow_stats['migration_success'] else "✗"
        phase_2 = "✓" if self.workflow_stats['processing_success'] else "✗"
        phase_2_5 = "✓" if self.workflow_stats['reextraction_success'] else "✗"
        phase_3 = "✓" if self.workflow_stats['scraper_success'] else "✗"
        
        logger.info(f"  {phase_1} Phase 1 (Migration): {self.workflow_stats['phase_times'].get('migration', 0):.1f}s")
        logger.info(f"  {phase_2} Phase 2 (Processing): {self.workflow_stats['phase_times'].get('processing', 0):.1f}s")
        logger.info(f"  {phase_2_5} Phase 2.5 (Comment Re-extraction): {self.workflow_stats['phase_times'].get('reextraction', 0):.1f}s")
        logger.info(f"  {phase_3} Phase 3 (Scraper): {self.workflow_stats['phase_times'].get('scraper', 0):.1f}s")
        
        success_count = sum([
            self.workflow_stats['migration_success'],
            self.workflow_stats['processing_success'],
            self.workflow_stats['reextraction_success'],
            self.workflow_stats['scraper_success']
        ])
        
        if success_count == 4:
            logger.info("🎉 ALL PHASES COMPLETED SUCCESSFULLY!")
            logger.info("Migration workflow finished. Your data is ready for the pipeline.")
        elif success_count >= 3:
            logger.warning("⚠️  MIGRATION MOSTLY SUCCESSFUL")
            logger.warning("Some phases had issues but core migration completed.")
        else:
            logger.error("❌ MIGRATION WORKFLOW FAILED")
            logger.error("Multiple phases failed. Please review logs and retry.")
        
        logger.info("\nNext Steps:")
        if self.workflow_stats['migration_success']:
            logger.info("✓ Data successfully transferred to new database schema")
        if self.workflow_stats['processing_success']:
            logger.info("✓ Document content cleaned and quality metrics populated")
        if self.workflow_stats['reextraction_success']:
            logger.info("✓ Comments re-extracted with consistent markdownify method")
        if self.workflow_stats['scraper_success']:
            logger.info("✓ Scraper verified migration and fetched new data")
        
        logger.info("\nRecommendations:")
        logger.info("• Review migration logs for any warnings or issues")
        logger.info("• Test pipeline components with migrated data")
        logger.info("• Monitor quality scores and extraction methods")
        logger.info("• Comments now consistently use markdownify extraction")
        logger.info("• Set up regular scraper runs to keep data current")
        
        logger.info("=" * 60)
    
    def run_complete_workflow(self, skip_processing: bool = False, skip_reextraction: bool = False, skip_scraper: bool = False) -> bool:
        """Run the complete migration workflow with optional skips."""
        logger.info("Starting complete migration workflow...")
        if self.dry_run:
            logger.info("DRY RUN MODE ENABLED")

        # Phase 0: Download Fresh DB
        if not self._download_fresh_db():
            logger.error("Failed to download fresh database. Aborting workflow.")
            self.generate_final_report()
            return False
        
        # Phase 1: Data Transfer Migration
        if not self.run_migration_phase():
            self.generate_final_report()
            return False
        
        # Phase 2: Processing (optional)
        if not skip_processing:
            if not self.run_processing_phase():
                logger.warning("Processing phase failed, continuing...")
        else:
            logger.info("Skipping processing phase")
        
        # Phase 2.5: Comment Re-extraction (optional)
        if not skip_reextraction:
            if not self.run_reextraction_phase():
                logger.warning("Comment re-extraction phase failed, continuing...")
        else:
            logger.info("Skipping comment re-extraction phase")
        
        # Phase 3: Scraper (optional)
        if not skip_scraper:
            if not self.run_scraper_phase():
                logger.warning("Scraper phase failed, continuing...")
        else:
            logger.info("Skipping scraper phase")
        
        # Final verification
        verification_success = self.verify_final_state()
        
        # Generate report
        self.generate_final_report()
        
        return verification_success

def main():
    parser = argparse.ArgumentParser(description="Complete Migration Workflow")
    parser.add_argument("--dry-run", action="store_true", 
                       help="Run in dry-run mode (no actual changes)")
    parser.add_argument("--skip-processing", action="store_true",
                       help="Skip the post-migration processing phase")
    parser.add_argument("--skip-reextraction", action="store_true",
                       help="Skip the comment re-extraction phase")
    parser.add_argument("--skip-scraper", action="store_true",
                       help="Skip the scraper verification phase")
    
    args = parser.parse_args()
    
    workflow = CompleteMigrationWorkflow(dry_run=args.dry_run)
    success = workflow.run_complete_workflow(
        skip_processing=args.skip_processing,
        skip_reextraction=args.skip_reextraction,
        skip_scraper=args.skip_scraper
    )
    
    if success:
        logger.info("Workflow completed successfully!")
        sys.exit(0)
    else:
        logger.error("Workflow completed with errors!")
        sys.exit(1)

if __name__ == "__main__":
    main() 