#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import argparse
from datetime import datetime

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
    consultation_data = metadata_result['consultation']
    
    # Check if consultation already exists
    existing_consultation = session.query(Consultation).filter_by(url=url).first()
    if existing_consultation:
        logger.info(f"Consultation already exists in database: {existing_consultation.title}")
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
            url=consultation_data['url'],
            description=consultation_data['description'],
            total_comments=consultation_data['total_comments'],
            accepted_comments=consultation_data['accepted_comments'],
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
    
    # Commit all changes to the database
    session.commit()
    
    logger.info(f"Scrape complete. Added/updated: 1 consultation, {article_count} articles, {comment_count} comments")
    return True

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
