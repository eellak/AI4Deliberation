#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import csv
import logging
import os
import requests
import time
from random import uniform
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Constants
BASE_URL = "https://www.opengov.gr/home/category/consultations"
OUTPUT_CSV = "all_consultations.csv"
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


def get_all_consultations():
    """Scrape all consultations from all pages"""
    all_consultations = []
    current_url = BASE_URL
    page_number = 1
    
    while current_url:
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
    
    logger.info(f"Total consultations found: {len(all_consultations)}")
    return all_consultations


def write_consultations_to_csv(consultations, csv_path):
    """Write consultation data to a CSV file"""
    try:
        with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['url', 'title', 'date']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            
            writer.writeheader()
            for consultation in consultations:
                writer.writerow(consultation)
            
        logger.info(f"Successfully wrote {len(consultations)} consultations to {csv_path}")
        return True
    
    except Exception as e:
        logger.error(f"Error writing to CSV file: {e}")
        return False


def analyze_consultations(consultations):
    """Analyze the consultations data for completeness"""
    total_count = len(consultations)
    missing_url = sum(1 for c in consultations if not c.get('url'))
    missing_title = sum(1 for c in consultations if not c.get('title'))
    missing_date = sum(1 for c in consultations if not c.get('date'))
    
    logger.info("=== Consultation Data Analysis ===")
    logger.info(f"Total consultations: {total_count}")
    logger.info(f"Missing URLs: {missing_url} ({missing_url/total_count*100:.2f}%)")
    logger.info(f"Missing titles: {missing_title} ({missing_title/total_count*100:.2f}%)")
    logger.info(f"Missing dates: {missing_date} ({missing_date/total_count*100:.2f}%)")
    logger.info("================================")


def main():
    """Main function to scrape all consultations and save to CSV"""
    logger.info("Starting consultation listing scraper")
    
    # Scrape all consultations
    all_consultations = get_all_consultations()
    
    if all_consultations:
        # Analyze the data
        analyze_consultations(all_consultations)
        
        # Write to CSV
        write_consultations_to_csv(all_consultations, OUTPUT_CSV)
        
        logger.info("Consultation listing complete!")
    else:
        logger.error("No consultations were found.")


if __name__ == "__main__":
    main()
