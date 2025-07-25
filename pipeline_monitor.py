#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Real-time Pipeline Monitor with Progress Tracking

Shows:
- Current pipeline stage
- Progress bars
- Anonymization statistics
- Error alerts
- Database status
"""

import os
import sys
import time
import sqlite3
import subprocess
from datetime import datetime
import argparse
import signal
from pathlib import Path

class PipelineMonitor:
    def __init__(self, log_dir="/mnt/data/AI4Deliberation/logs"):
        self.log_dir = log_dir
        self.running = True
        self.last_update = None
        
    def signal_handler(self, signum, frame):
        """Handle shutdown gracefully."""
        print("\n\nStopping monitor...")
        self.running = False
        
    def get_latest_log_file(self):
        """Find the most recent enhanced orchestrator log."""
        log_files = list(Path(self.log_dir).glob("enhanced_orchestrator_*.log"))
        if not log_files:
            return None
        return max(log_files, key=lambda f: f.stat().st_mtime)
        
    def get_database_stats(self, db_path):
        """Get anonymization statistics from database."""
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # Total consultations
            cursor.execute("SELECT COUNT(*) FROM consultations")
            total_consultations = cursor.fetchone()[0]
            
            # Total comments
            cursor.execute("SELECT COUNT(*) FROM comments")
            total_comments = cursor.fetchone()[0]
            
            # Anonymized comments
            cursor.execute("""
                SELECT COUNT(*) FROM comments 
                WHERE username LIKE 'user_%'
            """)
            anon_comments = cursor.fetchone()[0]
            
            # Non-anonymized comments
            cursor.execute("""
                SELECT COUNT(*) FROM comments 
                WHERE username IS NOT NULL 
                AND username != '' 
                AND username NOT LIKE 'user_%'
            """)
            non_anon_comments = cursor.fetchone()[0]
            
            conn.close()
            
            return {
                'total_consultations': total_consultations,
                'total_comments': total_comments,
                'anonymized_comments': anon_comments,
                'non_anonymized_comments': non_anon_comments,
                'anonymization_percentage': (anon_comments / total_comments * 100) if total_comments > 0 else 0
            }
        except Exception as e:
            return {'error': str(e)}
            
    def parse_log_progress(self, log_file):
        """Parse the log file to extract progress information."""
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                
            # Find progress indicators
            progress = {
                'stage': 'Unknown',
                'consultations_found': 0,
                'consultations_processed': 0,
                'current_consultation': None,
                'errors': [],
                'last_activity': None
            }
            
            for line in reversed(lines):  # Read from bottom up for latest info
                line = line.strip()
                
                if 'STARTING FULL DATABASE ANONYMIZATION' in line:
                    progress['stage'] = 'Full DB Anonymization'
                elif 'DISCOVERING NEW CONSULTATIONS' in line:
                    progress['stage'] = 'Discovery'
                elif 'Processing consultation' in line and '/consultation/' in line:
                    progress['stage'] = 'Scraping & Anonymizing'
                    # Extract consultation number
                    if '---' in line:
                        parts = line.split('/')
                        if len(parts) >= 2:
                            progress['current_consultation'] = parts[0].split()[-1]
                elif 'Found' in line and 'consultations in CSV' in line:
                    # Extract number of consultations
                    parts = line.split()
                    for i, part in enumerate(parts):
                        if part.isdigit() and i + 1 < len(parts) and parts[i+1] == 'consultations':
                            progress['consultations_found'] = int(part)
                elif 'Consultation' in line and 'processed:' in line and 'comments anonymized' in line:
                    progress['consultations_processed'] += 1
                elif '[ERROR]' in line:
                    progress['errors'].append(line)
                    
                # Get timestamp of last activity
                if line and not progress['last_activity']:
                    try:
                        timestamp = line.split(' - ')[0]
                        progress['last_activity'] = timestamp
                    except:
                        pass
                        
            return progress
            
        except Exception as e:
            return {'error': str(e)}
            
    def display_dashboard(self):
        """Display the monitoring dashboard."""
        # Clear screen
        os.system('clear' if os.name == 'posix' else 'cls')
        
        print("=" * 80)
        print("AI4DELIBERATION PIPELINE MONITOR".center(80))
        print("=" * 80)
        print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print()
        
        # Get latest log file
        log_file = self.get_latest_log_file()
        if not log_file:
            print("⚠️  No active pipeline found. Waiting for pipeline to start...")
            return
            
        # Parse progress
        progress = self.parse_log_progress(log_file)
        
        if 'error' in progress:
            print(f"❌ Error reading log: {progress['error']}")
            return
            
        # Display current stage
        print(f"📍 Current Stage: {progress['stage']}")
        if progress['last_activity']:
            print(f"⏰ Last Activity: {progress['last_activity']}")
        print()
        
        # Display progress
        if progress['consultations_found'] > 0:
            processed = progress['consultations_processed']
            total = progress['consultations_found']
            percentage = (processed / total * 100) if total > 0 else 0
            
            print(f"📊 Progress: {processed}/{total} consultations ({percentage:.1f}%)")
            
            # Progress bar
            bar_length = 50
            filled = int(bar_length * processed / total)
            bar = '█' * filled + '░' * (bar_length - filled)
            print(f"   [{bar}]")
            
            if progress['current_consultation']:
                print(f"   Currently processing: Consultation {progress['current_consultation']}")
        print()
        
        # Database statistics
        db_path = "/mnt/data/AI4Deliberation/deliberation_data_gr_MIGRATED_FRESH_20250602170747.db"
        if os.path.exists(db_path):
            stats = self.get_database_stats(db_path)
            
            if 'error' not in stats:
                print("📊 Database Statistics:")
                print(f"   Total Consultations: {stats['total_consultations']:,}")
                print(f"   Total Comments: {stats['total_comments']:,}")
                print(f"   Anonymized Comments: {stats['anonymized_comments']:,} ({stats['anonymization_percentage']:.1f}%)")
                print(f"   Non-anonymized Comments: {stats['non_anonymized_comments']:,}")
                
                # Anonymization progress bar
                if stats['total_comments'] > 0:
                    anon_percentage = stats['anonymization_percentage']
                    bar_length = 30
                    filled = int(bar_length * anon_percentage / 100)
                    bar = '█' * filled + '░' * (bar_length - filled)
                    print(f"   Anonymization: [{bar}] {anon_percentage:.1f}%")
        print()
        
        # Recent errors
        if progress['errors']:
            print("⚠️  Recent Errors:")
            for error in progress['errors'][-3:]:  # Show last 3 errors
                print(f"   {error[:100]}...")
        else:
            print("✅ No errors detected")
            
        print()
        print("Press Ctrl+C to stop monitoring")
        
    def monitor(self, refresh_interval=2):
        """Main monitoring loop."""
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        while self.running:
            try:
                self.display_dashboard()
                time.sleep(refresh_interval)
            except Exception as e:
                print(f"\nMonitor error: {e}")
                time.sleep(refresh_interval)
                
        print("\nMonitor stopped.")


def main():
    parser = argparse.ArgumentParser(description='Monitor AI4Deliberation Pipeline')
    parser.add_argument(
        '--log-dir',
        default='/mnt/data/AI4Deliberation/logs',
        help='Directory containing log files'
    )
    parser.add_argument(
        '--refresh',
        type=int,
        default=2,
        help='Refresh interval in seconds (default: 2)'
    )
    
    args = parser.parse_args()
    
    monitor = PipelineMonitor(args.log_dir)
    monitor.monitor(args.refresh)


if __name__ == "__main__":
    main()