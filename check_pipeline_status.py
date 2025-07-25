#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Quick diagnostic to check pipeline and database status."""

import os
import sys
import sqlite3
from datetime import datetime
from pathlib import Path

def check_database_status(db_path):
    """Check database anonymization status."""
    print("\n📊 DATABASE STATUS")
    print("=" * 60)
    
    if not os.path.exists(db_path):
        print(f"❌ Database not found: {db_path}")
        return
        
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get counts
        cursor.execute("SELECT COUNT(*) FROM consultations")
        total_consultations = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM comments")
        total_comments = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM comments WHERE username LIKE 'user_%'")
        anon_comments = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT COUNT(*) FROM comments 
            WHERE username IS NOT NULL 
            AND username != '' 
            AND username NOT LIKE 'user_%'
        """)
        non_anon_comments = cursor.fetchone()[0]
        
        # Get sample of non-anonymized usernames
        cursor.execute("""
            SELECT DISTINCT username FROM comments 
            WHERE username IS NOT NULL 
            AND username != '' 
            AND username NOT LIKE 'user_%'
            LIMIT 5
        """)
        non_anon_samples = [row[0] for row in cursor.fetchall()]
        
        conn.close()
        
        # Display results
        print(f"Total Consultations: {total_consultations:,}")
        print(f"Total Comments: {total_comments:,}")
        print(f"Anonymized Comments: {anon_comments:,}")
        print(f"Non-anonymized Comments: {non_anon_comments:,}")
        
        if total_comments > 0:
            anon_percentage = (anon_comments / total_comments) * 100
            print(f"Anonymization Rate: {anon_percentage:.1f}%")
            
        if non_anon_samples:
            print(f"\n⚠️  Sample non-anonymized usernames:")
            for username in non_anon_samples:
                print(f"   - {username}")
                
        if non_anon_comments == 0:
            print("\n✅ All comments are anonymized!")
        
    except Exception as e:
        print(f"❌ Error checking database: {e}")


def check_logs(log_dir):
    """Check recent pipeline logs."""
    print("\n📄 RECENT LOGS")
    print("=" * 60)
    
    if not os.path.exists(log_dir):
        print(f"❌ Log directory not found: {log_dir}")
        return
        
    # Find recent log files
    log_files = []
    for pattern in ["enhanced_orchestrator_*.log", "pipeline_orchestrator.log", "errors_*.log"]:
        log_files.extend(Path(log_dir).glob(pattern))
        
    if not log_files:
        print("No log files found")
        return
        
    # Sort by modification time
    log_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    
    print("Recent log files:")
    for log_file in log_files[:5]:
        mtime = datetime.fromtimestamp(log_file.stat().st_mtime)
        size_mb = log_file.stat().st_size / (1024 * 1024)
        print(f"  {log_file.name} - {mtime.strftime('%Y-%m-%d %H:%M:%S')} - {size_mb:.2f} MB")
        
    # Check for recent errors
    print("\nRecent errors:")
    error_count = 0
    for log_file in log_files[:3]:
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if '[ERROR]' in line or 'ERROR:' in line:
                        error_count += 1
                        if error_count <= 5:  # Show first 5 errors
                            print(f"  {line.strip()[:100]}...")
        except:
            pass
            
    if error_count == 0:
        print("  ✅ No errors found in recent logs")
    elif error_count > 5:
        print(f"  ... and {error_count - 5} more errors")


def check_processes():
    """Check if pipeline is running."""
    print("\n🔄 RUNNING PROCESSES")
    print("=" * 60)
    
    import subprocess
    
    # Check for orchestrator processes
    try:
        result = subprocess.run(
            ["pgrep", "-f", "pipeline_orchestrator"],
            capture_output=True,
            text=True
        )
        
        if result.stdout.strip():
            print("✅ Pipeline orchestrator is running")
            pids = result.stdout.strip().split('\n')
            for pid in pids:
                try:
                    cmd_result = subprocess.run(
                        ["ps", "-p", pid, "-o", "command="],
                        capture_output=True,
                        text=True
                    )
                    print(f"   PID {pid}: {cmd_result.stdout.strip()[:80]}...")
                except:
                    pass
        else:
            print("❌ No pipeline orchestrator process found")
            
    except Exception as e:
        print(f"Could not check processes: {e}")


def main():
    print("=" * 60)
    print("AI4DELIBERATION PIPELINE STATUS CHECK".center(60))
    print("=" * 60)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Check database
    db_path = "/mnt/data/AI4Deliberation/deliberation_data_gr_MIGRATED_FRESH_20250602170747.db"
    check_database_status(db_path)
    
    # Check logs
    log_dir = "/mnt/data/AI4Deliberation/logs"
    check_logs(log_dir)
    
    # Check processes
    check_processes()
    
    print("\n" + "=" * 60)
    print("\n📌 To run the enhanced pipeline:")
    print("   ./run_enhanced_pipeline.sh")
    print("\n📌 To monitor a running pipeline:")
    print("   ./run_enhanced_pipeline.sh --monitor-only")
    print("\n📌 To skip full DB anonymization:")
    print("   ./run_enhanced_pipeline.sh --skip-full-anonymization")


if __name__ == "__main__":
    main()