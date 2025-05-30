#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import argparse
import os
import sys
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import func

# Import our modules
from .db_models import init_db, Ministry, Consultation, Article, Comment, Document, Base
from .metadata_scraper import scrape_consultation_metadata
from .content_scraper import scrape_consultation_content
from .scrape_single_consultation import scrape_and_store

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def main():
    """Main entry point for the program"""
    parser = argparse.ArgumentParser(description='Scrape consultation data from OpenGov.gr and store in database')
    parser.add_argument('urls', metavar='URL', type=str, nargs='+',
                        help='One or more consultation URLs to scrape')
    parser.add_argument('--db-path', type=str, default='sqlite:///deliberation_data.db',
                        help='Database URL (default: sqlite:///deliberation_data.db)')
    
    args = parser.parse_args()
    
    # Initialize the database
    engine, Session = init_db(args.db_path)
    session = Session()
    
    try:
        success_count = 0
        for url in args.urls:
            if scrape_and_store(url, session):
                success_count += 1
        
        logger.info(f"Completed {success_count}/{len(args.urls)} consultations successfully")
    finally:
        session.close()

if __name__ == "__main__":
    main()
