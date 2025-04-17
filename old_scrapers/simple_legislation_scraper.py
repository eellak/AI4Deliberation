#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import csv
import time
import logging
import requests
from datetime import datetime
from bs4 import BeautifulSoup
import urllib.parse

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def parse_greek_date(date_string):
    """Parses a Greek date string in format 'DD Month YYYY, HH:MM' to a datetime object"""
    try:
        # Replace Greek month names with English equivalents
        greek_months = {
            'Ιανουαρίου': 'January',
            'Φεβρουαρίου': 'February',
            'Μαρτίου': 'March',
            'Απριλίου': 'April',
            'Μαΐου': 'May',
            'Ιουνίου': 'June',
            'Ιουλίου': 'July',
            'Αυγούστου': 'August',
            'Σεπτεμβρίου': 'September',
            'Οκτωβρίου': 'October',
            'Νοεμβρίου': 'November',
            'Δεκεμβρίου': 'December'
        }
        
        for greek, english in greek_months.items():
            date_string = date_string.replace(greek, english)
        
        # Parse the date string
        return datetime.strptime(date_string, '%d %B %Y, %H:%M')
    except Exception as e:
        logger.error(f"Error parsing date string '{date_string}': {e}")
        return None

def extract_content_text(element):
    """Extract text content from an HTML element, preserving some structure"""
    if not element:
        return ""
    
    # Get text with basic formatting preserved
    text_parts = []
    
    # Process paragraphs
    paragraphs = element.find_all('p')
    for p in paragraphs:
        text_parts.append(p.get_text(strip=True))
    
    # Process lists
    lists = element.find_all(['ul', 'ol'])
    for lst in lists:
        items = lst.find_all('li')
        for item in items:
            # Add bullet point for unordered lists
            if lst.name == 'ul':
                text_parts.append(f"• {item.get_text(strip=True)}")
            else:
                # For ordered lists, we don't know the exact number, so just use a bullet
                text_parts.append(f"- {item.get_text(strip=True)}")
    
    # Process headings
    headings = element.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
    for heading in headings:
        text_parts.append(heading.get_text(strip=True))
    
    return "\n\n".join(text_parts)

def scrape_legislation_metadata(url):
    """Scrape metadata about legislation using BeautifulSoup"""
    try:
        # Fetch the HTML content
        logger.info(f"Fetching URL: {url}")
        headers = {
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        
        # Parse HTML
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Initialize metadata dictionary
        metadata = {
            'url': url,
            'title': '',
            'ministry': '',
            'start_date': None,
            'end_date': None,
            'is_finished': False,
            'analysis_pdf_url': None,
            'deliberation_report_url': None,
            'accepted_comments': 0,
            'total_comments': 0,
            'start_minister_message': '',
            'end_minister_message': ''
        }
        
        # 1. Get ministry
        try:
            header_logo = soup.find('div', id='headerlogo')
            if header_logo:
                ministry_element = header_logo.find('h1').find('a')
                metadata['ministry'] = ministry_element.get_text(strip=True)
                logger.info(f"Found ministry: {metadata['ministry']}")
        except Exception as e:
            logger.error(f"Error extracting ministry: {e}")
        
        # 2. Get dates and status
        try:
            red_spot = soup.find('div', class_='sidespot red_spot')
            if red_spot:
                h4_element = red_spot.find('h4')
                if h4_element:
                    spans = h4_element.find_all('span')
                    if len(spans) >= 2:
                        start_date_str = spans[0].get_text(strip=True)
                        end_date_str = spans[1].get_text(strip=True)
                        
                        metadata['start_date'] = parse_greek_date(start_date_str)
                        metadata['end_date'] = parse_greek_date(end_date_str)
                        
                        logger.info(f"Start date: {metadata['start_date']}")
                        logger.info(f"End date: {metadata['end_date']}")
                
                # Check if deliberation is complete
                countdown_span = red_spot.find('span', id='cntdwn')
                if countdown_span and "Ολοκληρώθηκε" in countdown_span.get_text():
                    metadata['is_finished'] = True
                else:
                    # If no specific indicator, check the current date against end date
                    metadata['is_finished'] = metadata['end_date'] is not None and datetime.now() > metadata['end_date']
                
                logger.info(f"Deliberation status: {'Finished' if metadata['is_finished'] else 'Ongoing'}")
        except Exception as e:
            logger.error(f"Error extracting dates and status: {e}")
        
        # 3. Get PDF URLs
        try:
            orange_spot = soup.find('div', class_='sidespot orange_spot')
            if orange_spot:
                spans = orange_spot.find_all('span')
                
                for span in spans:
                    span_text = span.get_text(strip=True)
                    
                    # Look for analysis PDF
                    if "Ανάλυση Συνεπειών Ρύθμισης" in span_text:
                        link = span.find('a')
                        if link:
                            metadata['analysis_pdf_url'] = urllib.parse.urljoin(url, link['href'])
                            logger.info(f"Found analysis PDF: {metadata['analysis_pdf_url']}")
                    
                    # Look for deliberation report
                    if "ΕΚΘΕΣΗ ΕΠΙ ΤΗΣ ΔΗΜΟΣΙΑΣ ΔΙΑΒΟΥΛΕΥΣΗΣ" in span_text:
                        link = span.find('a')
                        if link:
                            metadata['deliberation_report_url'] = urllib.parse.urljoin(url, link['href'])
                            logger.info(f"Found deliberation report: {metadata['deliberation_report_url']}")
        except Exception as e:
            logger.error(f"Error extracting PDF URLs: {e}")
        
        # 4. Get comment statistics
        try:
            # Find all sidespot divs without specific colors
            sidespots = soup.find_all('div', class_='sidespot')
            for spot in sidespots:
                # Skip colored spots
                if 'red_spot' in spot.get('class', []) or 'orange_spot' in spot.get('class', []):
                    continue
                
                spot_text = spot.get_text()
                
                # Look for accepted comments pattern
                accepted_match = re.search(r'(\d+)\s+Σχόλια\s+επι\s+της', spot_text)
                if accepted_match:
                    metadata['accepted_comments'] = int(accepted_match.group(1))
                    logger.info(f"Found accepted comments: {metadata['accepted_comments']}")
                
                # Look for total comments pattern
                total_match = re.search(r'(\d+)\s+-\s+Όλα\s+τα\s+Σχόλια', spot_text)
                if total_match:
                    metadata['total_comments'] = int(total_match.group(1))
                    logger.info(f"Found total comments: {metadata['total_comments']}")
        except Exception as e:
            logger.error(f"Error extracting comment statistics: {e}")
        
        # 5. Get title and minister messages
        try:
            post_div = soup.find('div', class_='post clearfix')
            if post_div:
                # Get title
                title_element = post_div.find('h3')
                if title_element:
                    metadata['title'] = title_element.get_text(strip=True)
                    logger.info(f"Found title: {metadata['title']}")
                
                # Get end minister message (for finished deliberations)
                end_message_div = post_div.find('div', class_='post_content is_complete')
                if end_message_div:
                    metadata['end_minister_message'] = extract_content_text(end_message_div)
                    logger.info(f"Found end minister message: {len(metadata['end_minister_message'])} chars")
                
                # Get start minister message - we need to be careful not to get the same content twice
                # Look for a div with just class='post_content' and not 'post_content is_complete'
                all_content_divs = post_div.find_all('div', class_='post_content')
                
                # Find the div that only has class='post_content' without 'is_complete'
                for div in all_content_divs:
                    # Get the class attribute as a list
                    classes = div.get('class', [])
                    # Check if this div has only 'post_content' without 'is_complete'
                    if 'post_content' in classes and 'is_complete' not in classes:
                        metadata['start_minister_message'] = extract_content_text(div)
                        logger.info(f"Found start minister message: {len(metadata['start_minister_message'])} chars")
                        break
                
                # If we still don't have a start message and there's an end message, try to find any content
                # within the post div that might be our start message
                if not metadata['start_minister_message'] and len(all_content_divs) > 1:
                    # Find the div that is different from our end message div
                    for div in all_content_divs:
                        # Skip the div we already processed as end message
                        if div == end_message_div:
                            continue
                        # Use this div as our start message
                        metadata['start_minister_message'] = extract_content_text(div)
                        logger.info(f"Found start minister message (alt): {len(metadata['start_minister_message'])} chars")
                        break
        except Exception as e:
            logger.error(f"Error extracting minister messages: {e}")
        
        return metadata
    except Exception as e:
        logger.error(f"Error scraping legislation metadata: {e}")
        return None

def save_metadata_to_csv(metadata, output_file="legislation_metadata.csv"):
    """Save the extracted metadata to a CSV file"""
    try:
        # Define CSV field names
        fieldnames = [
            'title', 'ministry', 'url', 'start_date', 'end_date', 'is_finished',
            'analysis_pdf_url', 'deliberation_report_url',
            'accepted_comments', 'total_comments'
        ]
        
        # Check if file exists to determine if header is needed
        file_exists = os.path.isfile(output_file)
        
        # Open file in append mode
        with open(output_file, 'a', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            
            # Write header if file is new
            if not file_exists:
                writer.writeheader()
            
            # Write metadata row (excluding large text fields)
            row_data = {k: v for k, v in metadata.items() if k in fieldnames}
            writer.writerow(row_data)
        
        logger.info(f"Saved metadata to {output_file}")
        return True
    except Exception as e:
        logger.error(f"Error saving metadata to CSV file: {e}")
        return False

def save_content_to_text(metadata, base_filename):
    """Save the start and end minister messages to separate text files"""
    try:
        # Create output directory if it doesn't exist
        output_dir = "legislation_content"
        os.makedirs(output_dir, exist_ok=True)
        
        # Generate a safe filename
        safe_filename = re.sub(r'[^\w\s-]', '', base_filename)
        safe_filename = re.sub(r'[-\s]+', '_', safe_filename).strip('-_')
        
        # Save start minister message
        if metadata['start_minister_message']:
            start_filename = os.path.join(output_dir, f"{safe_filename}_start_message.txt")
            with open(start_filename, 'w', encoding='utf-8') as f:
                f.write(f"TITLE: {metadata['title']}\n")
                f.write(f"MINISTRY: {metadata['ministry']}\n")
                f.write(f"URL: {metadata['url']}\n")
                f.write(f"START DATE: {metadata['start_date']}\n")
                f.write(f"END DATE: {metadata['end_date']}\n")
                f.write(f"STATUS: {'Finished' if metadata['is_finished'] else 'Ongoing'}\n")
                f.write(f"COMMENTS: {metadata['accepted_comments']} accepted out of {metadata['total_comments']} total\n")
                f.write("\n" + "="*80 + "\n")
                f.write("START MINISTER MESSAGE:\n")
                f.write("="*80 + "\n\n")
                f.write(metadata['start_minister_message'])
            logger.info(f"Saved start minister message to {start_filename}")
        
        # Save end minister message if it exists
        if metadata['end_minister_message']:
            end_filename = os.path.join(output_dir, f"{safe_filename}_end_message.txt")
            with open(end_filename, 'w', encoding='utf-8') as f:
                f.write(f"TITLE: {metadata['title']}\n")
                f.write(f"MINISTRY: {metadata['ministry']}\n")
                f.write(f"URL: {metadata['url']}\n")
                f.write(f"START DATE: {metadata['start_date']}\n")
                f.write(f"END DATE: {metadata['end_date']}\n")
                f.write(f"STATUS: {'Finished' if metadata['is_finished'] else 'Ongoing'}\n")
                f.write(f"COMMENTS: {metadata['accepted_comments']} accepted out of {metadata['total_comments']} total\n")
                f.write("\n" + "="*80 + "\n")
                f.write("END MINISTER MESSAGE:\n")
                f.write("="*80 + "\n\n")
                f.write(metadata['end_minister_message'])
            logger.info(f"Saved end minister message to {end_filename}")
            
        return True
    except Exception as e:
        logger.error(f"Error saving content to text files: {e}")
        return False

def main():
    """Main function to run the scraper on test URLs"""
    # Test URLs
    test_urls = [
        "http://www.opengov.gr/koinsynoik/?p=9557",  # Complete deliberation
        "https://www.opengov.gr/ministryofjustice/?p=17805"  # Incomplete deliberation
    ]
    
    for url in test_urls:
        logger.info(f"\n{'='*80}\nTesting URL: {url}\n{'='*80}")
        
        # Scrape the legislation metadata
        metadata = scrape_legislation_metadata(url)
        
        if metadata:
            # Print metadata summary
            print(f"\nMetadata summary for {url}:")
            print(f"Title: {metadata['title']}")
            print(f"Ministry: {metadata['ministry']}")
            print(f"Status: {'Finished' if metadata['is_finished'] else 'Ongoing'}")
            print(f"Start date: {metadata['start_date']}")
            print(f"End date: {metadata['end_date']}")
            print(f"Comment stats: {metadata['accepted_comments']} accepted out of {metadata['total_comments']} total")
            print(f"Analysis PDF: {metadata['analysis_pdf_url']}")
            print(f"Deliberation report: {metadata['deliberation_report_url']}")
            print(f"Start message length: {len(metadata['start_minister_message'])} chars")
            print(f"End message length: {len(metadata['end_minister_message'])} chars")
            
            # Extract a filename from the URL
            post_id = url.split('?p=')[1]
            ministry_code = url.split('//')[1].split('.')[0]
            if ministry_code.startswith('www.'):
                ministry_code = ministry_code[4:]
            filename = f"{ministry_code}_{post_id}"
            
            # Save metadata to CSV
            save_metadata_to_csv(metadata)
            
            # Save content to text files
            save_content_to_text(metadata, filename)

if __name__ == "__main__":
    main()
