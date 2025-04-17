#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import logging
import requests
from bs4 import BeautifulSoup
from datetime import datetime
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

def extract_ministry_info(url):
    """Extract ministry information from the URL and page content"""
    try:
        # Parse URL to get ministry code
        parsed_url = urllib.parse.urlparse(url)
        hostname = parsed_url.netloc
        path_parts = parsed_url.path.strip('/').split('/')
        
        # Try to extract ministry code from URL
        ministry_code = None
        if hostname.startswith('www.opengov.gr'):
            ministry_code = path_parts[0] if path_parts else None
        else:
            # Handle case where ministry code is in subdomain
            domain_parts = hostname.split('.')
            if len(domain_parts) > 0 and 'opengov' in hostname:
                potential_code = domain_parts[0]
                if potential_code != 'www':
                    ministry_code = potential_code
        
        # Construct ministry base URL
        if ministry_code:
            ministry_base_url = f"https://www.opengov.gr/{ministry_code}/"
        else:
            ministry_base_url = url[:url.find('?')] if '?' in url else url
            
        return {
            'code': ministry_code,
            'url': ministry_base_url,
            'name': None  # We'll populate this with actual content scrape
        }
    except Exception as e:
        logger.error(f"Error extracting ministry info from URL {url}: {e}")
        return {
            'code': None,
            'url': None,
            'name': None
        }

def scrape_consultation_metadata(url):
    """Scrape metadata about a consultation/legislation and return structured data for DB"""
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
        
        # Extract post ID from URL
        post_id = None
        if '?p=' in url:
            post_id = url.split('?p=')[1].split('&')[0]
        
        # Initialize metadata dictionary
        metadata = {
            'post_id': post_id,
            'title': '',
            'start_minister_message': '',
            'end_minister_message': '',
            'start_date': None,
            'end_date': None,
            'is_finished': False,
            'url': url,
            'description': '',
            'total_comments': 0,
            'accepted_comments': 0
        }
        
        # Get ministry information
        ministry_info = extract_ministry_info(url)
        
        # 1. Get ministry name
        try:
            header_logo = soup.find('div', id='headerlogo')
            if header_logo:
                ministry_element = header_logo.find('h1').find('a')
                ministry_info['name'] = ministry_element.get_text(strip=True)
                logger.info(f"Found ministry: {ministry_info['name']}")
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
        
        # 3. Get related documents
        documents = []
        try:
            orange_spot = soup.find('div', class_='sidespot orange_spot')
            if orange_spot:
                spans = orange_spot.find_all('span', class_='file')
                
                for span in spans:
                    try:
                        link = span.find('a')
                        if link:
                            doc_title = link.get_text(strip=True)
                            doc_url = urllib.parse.urljoin(url, link['href'])
                            
                            doc_type = 'other'
                            if "Ανάλυση Συνεπειών Ρύθμισης" in doc_title:  # Analysis of Regulatory Consequences
                                doc_type = 'analysis'
                            elif "ΕΚΘΕΣΗ ΕΠΙ ΤΗΣ ΔΗΜΟΣΙΑΣ ΔΙΑΒΟΥΛΕΥΣΗΣ" in doc_title:  # Report on Public Deliberation
                                doc_type = 'deliberation_report'
                            elif "Σχέδιο Νόμου" in doc_title:  # Law Draft
                                doc_type = 'law_draft'
                            
                            documents.append({
                                'title': doc_title,
                                'url': doc_url,
                                'type': doc_type
                            })
                            
                            logger.info(f"Found document: {doc_title} ({doc_type})")
                    except Exception as e:
                        logger.error(f"Error processing document span: {e}")
        except Exception as e:
            logger.error(f"Error extracting documents: {e}")
        
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
                
                # Get start minister message
                # Find the div that only has class='post_content' without 'is_complete'
                all_content_divs = post_div.find_all('div', class_='post_content')
                for div in all_content_divs:
                    # Get the class attribute as a list
                    classes = div.get('class', [])
                    # Check if this div has only 'post_content' without 'is_complete'
                    if 'post_content' in classes and 'is_complete' not in classes:
                        metadata['start_minister_message'] = extract_content_text(div)
                        logger.info(f"Found start minister message: {len(metadata['start_minister_message'])} chars")
                        break
                
                # If we still don't have a start message and there's an end message, try to find any content
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
        
        # Return structured data
        return {
            'ministry': ministry_info,
            'consultation': metadata,
            'documents': documents
        }
    except Exception as e:
        logger.error(f"Error scraping consultation metadata: {e}")
        return None

if __name__ == "__main__":
    # Example usage
    test_url = "http://www.opengov.gr/koinsynoik/?p=9557"
    result = scrape_consultation_metadata(test_url)
    
    if result:
        print("\nConsultation Metadata:")
        for key, value in result['consultation'].items():
            if key != 'minister_message' and key != 'end_minister_message':
                print(f"{key}: {value}")
        
        print("\nMinistry Info:")
        for key, value in result['ministry'].items():
            print(f"{key}: {value}")
        
        print("\nDocuments:")
        for doc in result['documents']:
            print(f"- {doc['title']} ({doc['type']}): {doc['url']}")
        
        print(f"\nMinister Message Length: {len(result['consultation']['minister_message'])} chars")
        print(f"End Minister Message Length: {len(result['consultation']['end_minister_message'])} chars")
