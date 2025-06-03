#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import csv
import logging
import os
import requests
import time
import re # Added for URL pattern matching
from random import uniform
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import argparse
from datetime import datetime

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Constants
BASE_URL = "https://www.opengov.gr/home/category/consultations"
OUTPUT_CSV = "all_consultations.csv"
REQUEST_DELAY = (0.15, 0.25)  # Random delay between requests in seconds

# --- Date parsing utility ---
GREEK_MONTHS = {
    'Ιανουάριος': 1, 'Φεβρουάριος': 2, 'Μάρτιος': 3, 'Απρίλιος': 4,
    'Μάιος': 5, 'Ιούνιος': 6, 'Ιούλιος': 7, 'Αύγουστος': 8,
    'Σεπτέμβριος': 9, 'Οκτώβριος': 10, 'Νοέμβριος': 11, 'Δεκέμβριος': 12
}

def parse_greek_date(date_str):
    """Parse a Greek date string like '31 Μάιος, 2025' to a datetime.date object."""
    if not date_str:
        return None
    try:
        parts = date_str.replace(',', '').split() # "31", "Μάιος", "2025"
        day = int(parts[0])
        month_name = parts[1]
        year = int(parts[2])
        month = GREEK_MONTHS.get(month_name)
        if month:
            return datetime(year, month, day).date()
        else:
            logger.warning(f"Could not parse month: {month_name} in date string: {date_str}")
            return None
    except Exception as e:
        logger.error(f"Error parsing date string '{date_str}': {e}")
        return None
# --- End Date parsing utility ---

def get_consultation_links_from_page(url, latest_known_date=None):
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
                link_element = item.find('a')

                if not link_element or not link_element.has_attr('href'):
                    if item.find('p') and item.find('p').find('a'):
                        link_element = item.find('p').find('a')
                    elif item.find('h2') and item.find('h2').find('a'):
                        link_element = item.find('h2').find('a')
                    elif item.find('h3') and item.find('h3').find('a'):
                        link_element = item.find('h3').find('a')

                if not link_element or not link_element.has_attr('href') or not link_element.get_text(strip=True):
                    logger.warning(f"Could not find a suitable link/title element in list item: {item.get_text(strip=True)[:100]}...")
                    continue
                
                consultation_url = link_element['href']
                consultation_title = link_element.get_text(strip=True)
                
                # --- Validate URL structure ---
                # Expected pattern: http://www.opengov.gr/{any_path_part}/?p={digits}
                # or https://www.opengov.gr/{any_path_part}/?p={digits}
                url_pattern = r"https?://www\.opengov\.gr/.+?/\?p=\d+"
                if not re.match(url_pattern, consultation_url):
                    logger.warning(f"Skipping URL with invalid structure: {consultation_url} (Title: {consultation_title})")
                    continue
                # --- End URL validation ---
                
                # Extract the date (optional)
                date_span = item.find('span', class_='start')
                consultation_date_str = date_span.get_text(strip=True) if date_span else ""
                
                # --- Date cutoff logic ---
                if latest_known_date and consultation_date_str:
                    parsed_current_date = parse_greek_date(consultation_date_str)
                    if parsed_current_date and parsed_current_date <= latest_known_date:
                        logger.info(f"Reached consultation '{consultation_title}' (date {parsed_current_date}) which is on or before latest known date ({latest_known_date}). Stopping scrape for this page and further pages.")
                        return consultations, None # Signal to stop pagination
                # --- End Date cutoff logic ---
                
                consultations.append({
                    'url': consultation_url,
                    'title': consultation_title,
                    'date': consultation_date_str # Keep original string for CSV
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


def get_all_consultations(update_mode=False):
    """Scrape all consultations from all pages"""
    all_consultations = []
    current_url = BASE_URL
    page_number = 1
    latest_known_date = None

    if update_mode and os.path.exists(OUTPUT_CSV):
        try:
            with open(OUTPUT_CSV, 'r', newline='', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)
                max_date_so_far = None
                for row in reader:
                    parsed_date = parse_greek_date(row.get('date'))
                    if parsed_date:
                        if max_date_so_far is None or parsed_date > max_date_so_far:
                            max_date_so_far = parsed_date
                latest_known_date = max_date_so_far
                if latest_known_date:
                    logger.info(f"Update mode: Latest known consultation date from {OUTPUT_CSV} is {latest_known_date}.")
                else:
                    logger.warning(f"Update mode: Could not determine latest known date from {OUTPUT_CSV}. Proceeding with full scrape.")
        except Exception as e:
            logger.error(f"Error reading existing CSV for update mode: {e}. Proceeding with full scrape.")
    
    while current_url:
        # Get consultations from the current page
        logger.info(f"Processing page {page_number}")
        # Pass latest_known_date if in update_mode
        consultations_on_page, next_page_url = get_consultation_links_from_page(current_url, latest_known_date if update_mode else None)
        
        # Add consultations to the list
        if consultations_on_page:
            logger.info(f"Found {len(consultations_on_page)} consultations on page {page_number}")
            all_consultations.extend(consultations_on_page)
        else: # This can also be triggered if date cutoff happened mid-page and consultations_on_page is empty
            pass # No warning needed if it's due to date cutoff or genuine empty page
        
        # If next_page_url is None (either end of site or date cutoff), stop.
        if not next_page_url:
             if latest_known_date and update_mode and any(c for c in consultations_on_page if parse_greek_date(c['date']) and parse_greek_date(c['date']) <= latest_known_date):
                logger.info("Scraping stopped due to date cutoff.")
             else:
                logger.info("No more pages found or page returned no new items after date cutoff logic. Scraping complete for this run.")
             current_url = None # Ensure loop termination
        else:
            current_url = next_page_url
            page_number += 1
            delay = uniform(*REQUEST_DELAY)
            logger.info(f"Waiting {delay:.2f} seconds before next request...")
            time.sleep(delay)
    
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
    
    parser = argparse.ArgumentParser(description="Scrape consultations from opengov.gr")
    parser.add_argument("--update", action="store_true", help="Enable update mode: only scrape newer consultations than those in existing CSV.")
    args = parser.parse_args()

    logger.info(f"Starting consultation listing scraper (Update mode: {args.update})")
    
    # Scrape all consultations
    all_consultations = get_all_consultations(update_mode=args.update)
    
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
