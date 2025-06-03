#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import logging
import os
import sys
from datetime import datetime
from sqlalchemy import func
import requests
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from random import uniform

# Add current directory to path for imports when called from other locations
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import our modules
from .db_models import init_db, Ministry, Consultation, Article, Comment, Document, Base
from .metadata_scraper import scrape_consultation_metadata
from .content_scraper import scrape_consultation_content
from .utils import get_request_headers

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def scrape_and_store(url, session, selective_update=False, existing_cons=None):
    """Scrape a consultation URL and store all data in the database.
    
    If selective_update is True and existing_cons is provided, only updates
    minister messages, comments, and document links for unfinished consultations.
    
    Returns True if successful, and a dictionary of changes when selective_update is True.
    """
    logger.info(f"Starting {'selective update' if selective_update else 'full scrape'} of URL: {url}")
    
    # Initialize change tracking dictionary
    changes = {
        'new_comments': 0,
        'new_documents': 0,
        'status_change': False,
        'total_comments_change': 0,
        'start_message_changed': False,
        'end_message_changed': False
    }
    
    # Step 1: Scrape metadata
    metadata_result = scrape_consultation_metadata(url)
    if not metadata_result:
        logger.error(f"Failed to scrape metadata from {url}")
        return False, None
    
    # Validate post_id - if it's None, we can't proceed
    consultation_data = metadata_result['consultation']
    if not consultation_data['post_id']:
        logger.error(f"Missing post_id for URL: {url}. This consultation was likely redirected or no longer exists.")
        return False, None
    
    # Step 2: Extract ministry data and find or create ministry record
    ministry_data = metadata_result['ministry']
    ministry = session.query(Ministry).filter_by(code=ministry_data['code']).first()
    
    if not ministry:
        logger.info(f"Creating new ministry record for {ministry_data['name']}")
        ministry = Ministry(
            code=ministry_data['code'],
            name=ministry_data['name'],
            url=ministry_data['url']
        )
        session.add(ministry)
        session.flush()  # Get the ID without committing
    
    # Step 3: Strict consultation existence check
    # post_id was already validated above
    post_id = consultation_data['post_id']
    
    # STRICT DUPLICATE PREVENTION: Check by URL first (most reliable), then by post_id
    normalized_url = url.replace('http://', '').replace('https://', '')
    
    # Primary check: Look for existing consultation by normalized URL
    existing_consultation = None
    consultations = session.query(Consultation).all()
    for cons in consultations:
        norm_cons_url = cons.url.replace('http://', '').replace('https://', '')
        if norm_cons_url == normalized_url:
            existing_consultation = cons
            logger.info(f"Found existing consultation by URL match: {cons.title}")
            break
    
    # Secondary check: If not found by URL, check by post_id as backup
    if not existing_consultation:
        existing_consultation = session.query(Consultation).filter_by(post_id=post_id).first()
        if existing_consultation:
            logger.info(f"Found existing consultation by post_id match: {existing_consultation.title}")
    
    # STRICT HANDLING LOGIC
    if existing_consultation:
        logger.info(f"Consultation already exists: {existing_consultation.title}")
        logger.info(f"  ID: {existing_consultation.id}")
        logger.info(f"  Finished: {existing_consultation.is_finished}")
        logger.info(f"  URL: {existing_consultation.url}")
        
        # RULE 1: If consultation is finished, NEVER modify it
        if existing_consultation.is_finished:
            logger.warning("⚠️  CONSULTATION IS FINISHED - No updates allowed")
            logger.info("📋 Existing consultation data remains unchanged")
            
            # Return consultation ID for reporting but don't modify anything
            session.commit()  # Commit any pending changes (though there shouldn't be any)
            
            if selective_update:
                return True, {
                    'new_comments': 0,
                    'new_documents': 0,
                    'status_change': False,
                    'total_comments_change': 0,
                    'start_message_changed': False,
                    'end_message_changed': False,
                    'message': 'Consultation is finished - no updates performed'
                }
            else:
                return True, existing_consultation.id
        
        # RULE 2: If consultation is unfinished, only update comments and documents
        logger.info("🔄 CONSULTATION IS UNFINISHED - Checking for new comments and documents")
        
        # Update only basic metadata that might change for unfinished consultations
        old_total_comments = existing_consultation.total_comments or 0
        existing_consultation.total_comments = consultation_data['total_comments']
        existing_consultation.end_minister_message = consultation_data['end_minister_message']  # This might be added when consultation finishes
        
        # Check if consultation became finished
        was_unfinished = not existing_consultation.is_finished
        existing_consultation.is_finished = consultation_data['is_finished']
        
        if was_unfinished and consultation_data['is_finished']:
            logger.info("🏁 Consultation status changed: UNFINISHED → FINISHED")
        
        session.flush()
        consultation = existing_consultation
        
    else:
        # RULE 3: New consultation - full scrape allowed
        logger.info(f"✅ NEW CONSULTATION - Creating new record: {consultation_data['title']}")
        consultation = Consultation(
            post_id=consultation_data['post_id'],
            title=consultation_data['title'],
            start_minister_message=consultation_data['start_minister_message'],
            end_minister_message=consultation_data['end_minister_message'],
            start_date=consultation_data['start_date'],
            end_date=consultation_data['end_date'],
            is_finished=consultation_data['is_finished'],
            url=url,
            total_comments=consultation_data['total_comments'],
            accepted_comments=0,  # Initialize to 0, will be updated with actual comment count below
            ministry_id=ministry.id
        )
        session.add(consultation)
        session.flush()  # Get the ID without committing
    
    # Step 4: Create document records
    for doc_data in metadata_result['documents']:
        # Check if document already exists
        existing_doc = session.query(Document).filter_by(url=doc_data['url']).first()
        if not existing_doc:
            logger.info(f"Adding document: {doc_data['title']}")
            document = Document(
                title=doc_data['title'],
                url=doc_data['url'],
                type=doc_data['type'],
                consultation_id=consultation.id
            )
            session.add(document)
            
            # If we're doing a selective update, track new documents
            if selective_update:
                changes['new_documents'] += 1
    
    # Step 5: Scrape article content and comments
    articles_data = scrape_consultation_content(url)
    if not articles_data:
        logger.error(f"Failed to scrape articles from {url}")
        # Continue anyway, as we might have metadata
        
    # If we're doing a selective update of an unfinished consultation that is now finished,
    # record this status change
    if selective_update and existing_cons:
        if not existing_cons.is_finished and consultation_data['is_finished']:
            changes['status_change'] = True
            logger.info("Consultation status changed from unfinished to finished")
    
    # Step 6: Create article and comment records
    article_count = 0
    comment_count = 0
    
    # If this is a selective update, we only need to track changes to comments
    if selective_update and existing_cons:
        # Track changes to minister messages
        old_start_message = existing_cons.start_minister_message or ""
        new_start_message = consultation_data['start_minister_message'] or ""
        if old_start_message != new_start_message:
            changes['start_message_changed'] = True
            logger.info(f"Start minister message changed: {len(old_start_message)} chars -> {len(new_start_message)} chars")
            
        old_end_message = existing_cons.end_minister_message or ""
        new_end_message = consultation_data['end_minister_message'] or ""
        if old_end_message != new_end_message:
            changes['end_message_changed'] = True
            logger.info(f"End minister message changed: {len(old_end_message)} chars -> {len(new_end_message)} chars")
            
        # Track changes to total comments
        old_total = existing_cons.total_comments or 0
        new_total = consultation_data['total_comments'] or 0
        if old_total != new_total:
            changes['total_comments_change'] = new_total - old_total
            logger.info(f"Total comments changed: {old_total} -> {new_total} (change: {changes['total_comments_change']})")
    
    for article_data in articles_data:
        # Check if article already exists
        existing_article = session.query(Article).filter_by(url=article_data['url']).first()
        
        if existing_article:
            article = existing_article
            logger.info(f"Article already exists: {article.title}")
        else:
            logger.info(f"Adding article: {article_data['title']}")
            article = Article(
                title=article_data['title'],
                content=article_data['content'],
                raw_html=article_data.get('raw_html', ''),  # Include raw HTML content
                url=article_data['url'],
                consultation_id=consultation.id
            )
            session.add(article)
            session.flush()  # Get the ID without committing
            article_count += 1
        
        # Add comments for this article
        for comment_data in article_data['comments']:
            # Check if comment already exists (by comment_id and article_id)
            existing_comment = session.query(Comment).filter_by(
                comment_id=comment_data['comment_id'],
                article_id=article.id
            ).first()
            
            if not existing_comment:
                logger.info(f"Adding comment by {comment_data['username']}")
                comment = Comment(
                    comment_id=comment_data['comment_id'],
                    username=comment_data['username'],
                    date=comment_data['date'],
                    content=comment_data['content'],
                    article_id=article.id
                )
                session.add(comment)
                comment_count += 1
                
                # If we're doing a selective update, track new comments
                if selective_update:
                    changes['new_comments'] += 1
    
    # Calculate accepted_comments as the sum of all comments in articles
    total_comment_count = session.query(func.count(Comment.id)).join(Article).filter(Article.consultation_id == consultation.id).scalar() or 0
    logger.info(f"Calculated actual comment count from articles: {total_comment_count}")
    
    # Update accepted_comments with the actual count
    consultation.accepted_comments = total_comment_count
    
    try:
        session.commit()
        logger.info(f"Successfully processed and committed data for consultation ID: {consultation.id}")
        if selective_update:
            return True, changes
        else:
            return True, consultation.id
    except Exception as e:
        logger.error(f"Database commit failed for {url}: {e}")
        session.rollback()
        if selective_update:
            return False, changes
        else:
            return False, None

def main():
    """Main entry point for the program"""
    parser = argparse.ArgumentParser(description='Scrape consultation data from OpenGov.gr and store in database')
    parser.add_argument('urls', metavar='URL', type=str, nargs='+',
                        help='One or more consultation URLs to scrape')
    # Use the project root directory for the default database path
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    default_db_path = f'sqlite:///{os.path.join(project_root, "deliberation_data_gr.db")}'
    
    parser.add_argument('--db-path', type=str, default=default_db_path,
                        help=f'Database URL (default: {default_db_path})')
    
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
