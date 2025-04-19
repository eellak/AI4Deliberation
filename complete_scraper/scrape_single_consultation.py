#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import logging
import os
import sys
from datetime import datetime
from sqlalchemy import func

# Add current directory to path for imports when called from other locations
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import our modules
from db_models import init_db, Ministry, Consultation, Article, Comment, Document, Base
from metadata_scraper import scrape_consultation_metadata
from content_scraper import scrape_consultation_content

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def scrape_and_store(url, session):
    """Scrape a consultation URL and store all data in the database"""
    logger.info(f"Starting scrape of URL: {url}")
    
    # Step 1: Scrape metadata
    metadata_result = scrape_consultation_metadata(url)
    if not metadata_result:
        logger.error(f"Failed to scrape metadata from {url}")
        return False
    
    # Validate post_id - if it's None, we can't proceed
    consultation_data = metadata_result['consultation']
    if not consultation_data['post_id']:
        logger.error(f"Missing post_id for URL: {url}. This consultation was likely redirected or no longer exists.")
        return False
    
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
    
    # Step 3: Create consultation record
    # post_id was already validated above
    post_id = consultation_data['post_id']
    
    # Normalize URL for comparison (remove http/https differences)
    normalized_url = url.replace('http://', '').replace('https://', '')
    
    # Check if consultation already exists by post_id (more reliable than URL)
    existing_consultation = session.query(Consultation).filter_by(post_id=post_id).first()
    
    # If not found by post_id, try with normalized URL as backup
    if not existing_consultation:
        existing_consultations = session.query(Consultation).all()
        for cons in existing_consultations:
            norm_cons_url = cons.url.replace('http://', '').replace('https://', '')
            if norm_cons_url == normalized_url:
                existing_consultation = cons
                logger.info(f"Found consultation by normalized URL")
                break
    
    if existing_consultation:
        logger.info(f"Consultation already exists in database: {existing_consultation.title}")
        
        # Update the existing consultation with new metadata
        logger.info("Updating consultation with latest metadata")
        
        # Store original values for comparison
        original_values = {
            'title': existing_consultation.title,
            'start_date': existing_consultation.start_date,
            'end_date': existing_consultation.end_date,
            'is_finished': existing_consultation.is_finished,
            'total_comments': existing_consultation.total_comments,
            'start_minister_message': len(existing_consultation.start_minister_message or ''),
            'end_minister_message': len(existing_consultation.end_minister_message or '')
        }
        
        # Update fields - using direct property assignment to ensure values are set
        existing_consultation.title = consultation_data['title']
        existing_consultation.start_minister_message = consultation_data['start_minister_message']
        existing_consultation.end_minister_message = consultation_data['end_minister_message']
        existing_consultation.start_date = consultation_data['start_date']
        existing_consultation.end_date = consultation_data['end_date']
        existing_consultation.is_finished = consultation_data['is_finished']
        existing_consultation.total_comments = consultation_data['total_comments']
        
        # Force SQLAlchemy to mark all fields as dirty to ensure update
        session.add(existing_consultation)
        session.flush()
        
        # Log changes
        new_values = {
            'title': existing_consultation.title,
            'start_date': existing_consultation.start_date,
            'end_date': existing_consultation.end_date,
            'is_finished': existing_consultation.is_finished,
            'total_comments': existing_consultation.total_comments,
            'start_minister_message': len(existing_consultation.start_minister_message or ''),
            'end_minister_message': len(existing_consultation.end_minister_message or '')
        }
        
        # Log what fields were updated
        for field, old_val in original_values.items():
            new_val = new_values[field]
            if field.endswith('_message'):
                if old_val != new_val:
                    logger.info(f"Updated {field}: {old_val} chars -> {new_val} chars")
            elif old_val != new_val:
                logger.info(f"Updated {field}: {old_val} -> {new_val}")
        
        consultation = existing_consultation
    else:
        logger.info(f"Creating new consultation record: {consultation_data['title']}")
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
    
    # Step 5: Scrape article content and comments
    articles_data = scrape_consultation_content(url)
    if not articles_data:
        logger.error(f"Failed to scrape articles from {url}")
        # Continue anyway, as we might have metadata
    
    # Step 6: Create article and comment records
    article_count = 0
    comment_count = 0
    
    for article_data in articles_data:
        # Check if article already exists
        existing_article = session.query(Article).filter_by(url=article_data['url']).first()
        
        if existing_article:
            article = existing_article
            logger.info(f"Article already exists: {article.title}")
        else:
            logger.info(f"Adding article: {article_data['title']}")
            article = Article(
                post_id=article_data['post_id'],
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
    
    # Calculate accepted_comments as the sum of all comments in articles
    total_comment_count = session.query(func.count(Comment.id)).join(Article).filter(Article.consultation_id == consultation.id).scalar() or 0
    logger.info(f"Calculated actual comment count from articles: {total_comment_count}")
    
    # Update accepted_comments with the actual count
    consultation.accepted_comments = total_comment_count
    
    # Commit all changes to the database
    session.commit()
    
    logger.info(f"Scrape complete. Added/updated: {article_count} articles, {comment_count} comments")
    return True

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
