#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import os
import time
import argparse
from random import uniform
from bs4 import BeautifulSoup
import requests
from urllib.parse import urljoin

# Import our modules
from db_models import Ministry, Consultation, Article, Comment, Document, init_db
from scrape_single_consultation import scrape_and_store

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Constants
BASE_URL = "https://www.opengov.gr/home/category/consultations"
REQUEST_DELAY = (0.15, 0.25)  # Random delay between requests in seconds


def get_consultation_links_from_page(url):
    """Extract all consultation links and titles from a page"""
    logger.info(f"Fetching consultation links from: {url}")
    
    try:
        # Fetch the HTML content
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        
        # Parse the HTML
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Find the main content div that contains the consultation listings
        content_div = soup.find('div', class_='downspace_item_content archive_list')
        if not content_div:
            logger.error(f"Could not find consultation listings div on page: {url}")
            return [], None
        
        # Extract all consultation items
        consultations = []
        list_items = content_div.find_all('li')
        
        for item in list_items:
            try:
                # Extract the link and title
                link_element = item.find('p').find('a')
                if not link_element:
                    continue
                
                consultation_url = link_element['href']
                consultation_title = link_element.get_text(strip=True)
                
                # Extract the date (optional)
                date_span = item.find('span', class_='start')
                consultation_date = date_span.get_text(strip=True) if date_span else ""
                
                consultations.append({
                    'url': consultation_url,
                    'title': consultation_title,
                    'date': consultation_date
                })
                
            except Exception as e:
                logger.error(f"Error extracting consultation details: {e}")
        
        # Find the next page link
        pagination = soup.find('div', class_='wp-pagenavi')
        next_page_url = None
        
        if pagination:
            # Look for the nextpostslink
            next_link = pagination.find('a', class_='nextpostslink')
            if next_link and next_link.has_attr('href'):
                next_page_url = next_link['href']
                logger.info(f"Found next page link: {next_page_url}")
        
        return consultations, next_page_url
    
    except Exception as e:
        logger.error(f"Error fetching page {url}: {e}")
        return [], None


def get_all_consultation_links(start_page=1, end_page=None):
    """Get all consultation links from all pages within the specified range"""
    all_consultations = []
    current_url = BASE_URL
    page_number = 1
    
    # Skip to the start page if needed
    while page_number < start_page and current_url:
        logger.info(f"Skipping to page {start_page}, currently at page {page_number}")
        _, next_page_url = get_consultation_links_from_page(current_url)
        if next_page_url:
            current_url = next_page_url
            page_number += 1
        else:
            logger.error(f"Could not navigate to page {start_page}")
            return []
    
    # Scrape pages within the range
    while current_url:
        # Stop if we've reached the end page
        if end_page and page_number > end_page:
            logger.info(f"Reached end page {end_page}. Stopping.")
            break
            
        # Get consultations from the current page
        logger.info(f"Processing page {page_number}")
        consultations, next_page_url = get_consultation_links_from_page(current_url)
        
        # Add consultations to the list
        if consultations:
            logger.info(f"Found {len(consultations)} consultations on page {page_number}")
            all_consultations.extend(consultations)
        else:
            logger.warning(f"No consultations found on page {page_number}")
        
        # Move to the next page
        if next_page_url:
            current_url = next_page_url
            page_number += 1
            
            # Add a small delay to avoid overloading the server
            delay = uniform(*REQUEST_DELAY)
            logger.info(f"Waiting {delay:.2f} seconds before next request...")
            time.sleep(delay)
        else:
            logger.info("No more pages found. Scraping complete.")
            current_url = None
    
    logger.info(f"Total consultation links found: {len(all_consultations)}")
    return all_consultations


def scrape_consultations_to_db(consultation_links, db_url, batch_size=20, max_count=None, force_scrape=False):
    """Scrape consultations and store in database"""
    # Initialize database
    engine, Session = init_db(db_url)
    session = Session()
    
    # Track stats
    total_count = len(consultation_links)
    processed_count = 0
    success_count = 0
    skipped_count = 0
    
    logger.info(f"Starting to scrape {total_count} consultations to database")
    
    try:
        # Process consultations in batches
        for i, consultation in enumerate(consultation_links):
            # Check if we've reached the maximum
            if max_count and processed_count >= max_count:
                logger.info(f"Reached maximum count of {max_count} consultations. Stopping.")
                break
                
            url = consultation['url']
            post_id = url.split('?p=')[-1] if '?p=' in url else None
            
            # Check if this consultation already exists in the database
            existing = None
            if not force_scrape and post_id:
                existing = session.query(Consultation).filter_by(post_id=post_id).first()
                
                # If not found by post_id, try with URL
                if not existing:
                    normalized_url = url.replace('http://', '').replace('https://', '')
                    existing_consultations = session.query(Consultation).all()
                    for cons in existing_consultations:
                        norm_cons_url = cons.url.replace('http://', '').replace('https://', '')
                        if norm_cons_url == normalized_url:
                            existing = cons
                            break
            
            if existing and not force_scrape:
                logger.info(f"Skipping existing consultation: {url}")
                skipped_count += 1
            else:
                # Scrape and store this consultation
                logger.info(f"Processing consultation {processed_count+1}/{total_count}: {url}")
                
                try:
                    # Use the existing scrape_and_store function
                    result = scrape_and_store(url, session)
                    if result:
                        success_count += 1
                except Exception as e:
                    logger.error(f"Error processing consultation {url}: {e}")
            
            processed_count += 1
            
            # Commit in batches to avoid large transactions
            if processed_count % batch_size == 0:
                logger.info(f"Committing batch of {batch_size} consultations")
                session.commit()
                
            # Add a small delay between consultations
            if i < len(consultation_links) - 1:
                delay = uniform(*REQUEST_DELAY)
                logger.info(f"Waiting {delay:.2f} seconds before next consultation...")
                time.sleep(delay)
        
        # Final commit for any remaining consultations
        session.commit()
        
    except Exception as e:
        logger.error(f"Error in batch processing: {e}")
        session.rollback()
    finally:
        session.close()
    
    # Report results
    logger.info("=== Scraping Results ===")
    logger.info(f"Total consultations processed: {processed_count}/{total_count}")
    logger.info(f"Successfully scraped: {success_count}")
    logger.info(f"Skipped (already in database): {skipped_count}")
    logger.info(f"Failed: {processed_count - success_count - skipped_count}")
    logger.info("=======================")
    
    return success_count


def main():
    """Main function to scrape all consultations and store in DB"""
    parser = argparse.ArgumentParser(description='Scrape all consultations from OpenGov.gr and store in database')
    
    # Use the project root directory for the default database path
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    default_db_path = f'sqlite:///{os.path.join(project_root, "deliberation_data_gr.db")}'
    
    parser.add_argument('--db-path', type=str, default=default_db_path,
                        help=f'Database URL (default: {default_db_path})')
    parser.add_argument('--start-page', type=int, default=1,
                       help='Starting page number (default: 1)')
    parser.add_argument('--end-page', type=int, default=None,
                       help='Ending page number (default: scrape all pages)')
    parser.add_argument('--max-count', type=int, default=None,
                       help='Maximum number of consultations to scrape (default: all)')
    parser.add_argument('--batch-size', type=int, default=10,
                       help='Commit to database after processing this many consultations (default: 10)')
    parser.add_argument('--force-scrape', action='store_true',
                       help='Force scrape even if consultation already exists in database')
    
    args = parser.parse_args()
    
    logger.info("Starting mass consultation scraper")
    
    # Get all consultation links
    consultation_links = get_all_consultation_links(args.start_page, args.end_page)
    
    if not consultation_links:
        logger.error("No consultation links found to process")
        return
    
    # Scrape consultations and store in DB
    success_count = scrape_consultations_to_db(
        consultation_links, 
        args.db_path,
        batch_size=args.batch_size,
        max_count=args.max_count,
        force_scrape=args.force_scrape
    )
    
    logger.info(f"Consultation scraping complete! Successfully stored {success_count} consultations.")


if __name__ == "__main__":
    main()
