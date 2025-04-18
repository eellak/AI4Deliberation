#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import logging
import requests
from bs4 import BeautifulSoup

# Import utilities from shared module
from utils import (
    parse_greek_date, 
    extract_content_text, 
    find_element_with_fallbacks,
    extract_post_id, 
    build_absolute_url,
    extract_ministry_info,
    get_request_headers
)

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def scrape_consultation_metadata(url):
    """Scrape metadata about a consultation/legislation and return structured data for DB"""
    try:
        # Fetch the HTML content
        logger.info(f"Fetching URL: {url}")
        response = requests.get(url, headers=get_request_headers(), timeout=30, allow_redirects=True)
        response.raise_for_status()
        
        # Get the final URL after any redirections
        final_url = response.url
        if final_url != url:
            logger.info(f"URL was redirected: {url} -> {final_url}")
            url = final_url
        
        # Parse HTML
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Initialize metadata dictionary
        metadata = {
            'post_id': extract_post_id(url),  # Now using the final URL after redirects
            'title': '',
            'start_minister_message': '',
            'end_minister_message': '',
            'start_date': None,
            'end_date': None,
            'is_finished': None,
            'url': url,  # This is now the final URL after redirects
            'total_comments': 0,
            'accepted_comments': None
        }
        
        # Get ministry information
        ministry_info = extract_ministry_info(url)
        
        # 1. Get ministry name
        header_logo = soup.find('div', id='headerlogo')
        if header_logo:
            ministry_element = header_logo.find('h1', recursive=True).find('a')
            if ministry_element:
                ministry_info['name'] = ministry_element.get_text(strip=True)
                logger.info(f"Found ministry: {ministry_info['name']}")
        
        # 2. Get dates and status
        try:
            # Look for a red sidespot first (most common case)
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
                    logger.info("Deliberation marked as finished by 'Ολοκληρώθηκε' text")
                elif metadata['end_date']:
                    # If no specific indicator, check against current date
                    from datetime import datetime
                    metadata['is_finished'] = datetime.now() > metadata['end_date']
                    logger.info(f"Deliberation status determined by date: {'Finished' if metadata['is_finished'] else 'Ongoing'}")
            else:
                # Try alternate approaches if no red_spot div
                # Some consultations might use different styling or structure
                sidespots = soup.find_all('div', class_='sidespot')
                for spot in sidespots:
                    spot_text = spot.get_text()
                    if "Διάστημα Διαβούλευσης" in spot_text:
                        # Look for date pattern like "12 Μαρτίου 2025, 14:30"
                        date_pattern = r'(\d+)\s+([Α-Ωα-ωίϊΐόάέύϋΰήώ]+)\s+(\d{4}),\s+(\d{1,2}):(\d{2})'
                        date_matches = list(re.finditer(date_pattern, spot_text))
                        
                        if len(date_matches) >= 2:
                            start_date_str = date_matches[0].group(0)
                            end_date_str = date_matches[1].group(0)
                            
                            metadata['start_date'] = parse_greek_date(start_date_str)
                            metadata['end_date'] = parse_greek_date(end_date_str)
                            
                            logger.info(f"Found dates using alternate pattern: {metadata['start_date']} to {metadata['end_date']}")
                        
                        # Check for completion keywords
                        if "Ολοκληρώθηκε" in spot_text or "ολοκληρωμένη" in spot_text.lower():
                            metadata['is_finished'] = True
                            logger.info("Deliberation marked as finished through alternate text detection")
                        break
            
            logger.info(f"Final deliberation status: {'Finished' if metadata['is_finished'] else 'Ongoing'}")
        except Exception as e:
            logger.error(f"Error extracting dates and status: {e}")
        
        # 3. Get related documents
        documents = []
        orange_spot = soup.find('div', class_='sidespot orange_spot')
        if orange_spot:
            file_spans = orange_spot.find_all('span', class_='file')
            
            for span in file_spans:
                link = span.find('a')
                if link:
                    doc_title = link.get_text(strip=True)
                    doc_url = build_absolute_url(url, link['href'])
                    
                    # Determine document type
                    doc_type = 'other'
                    if "Ανάλυση Συνεπειών Ρύθμισης" in doc_title:
                        doc_type = 'analysis'
                    elif "ΕΚΘΕΣΗ ΕΠΙ ΤΗΣ ΔΗΜΟΣΙΑΣ ΔΙΑΒΟΥΛΕΥΣΗΣ" in doc_title:
                        doc_type = 'deliberation_report'
                    elif "Σχέδιο Νόμου" in doc_title:
                        doc_type = 'law_draft'
                    
                    documents.append({
                        'title': doc_title,
                        'url': doc_url,
                        'type': doc_type
                    })
                    
                    logger.info(f"Found document: {doc_title} ({doc_type})")
        
        # 4. Get comment statistics
        try:
            sidespots = soup.find_all('div', class_='sidespot')
            for spot in sidespots:
                # Skip colored spots
                if 'red_spot' in spot.get('class', []) or 'orange_spot' in spot.get('class', []):
                    continue
                
                spot_text = spot.get_text()
                
                # Try multiple patterns for comment statistics
                # Pattern for accepted comments
                accepted_patterns = [
                    r'(\d+)\s+Σχόλια\s+επι\s+της',
                    r'(\d+)\s+Σχόλια\s+επί\s+της',
                    r'(\d+)\s+σχόλια\s+επι\s+της',
                    r'(\d+)\s+σχόλια\s+επί\s+της'
                ]
                
                for pattern in accepted_patterns:
                    accepted_match = re.search(pattern, spot_text)
                    if accepted_match:
                        metadata['accepted_comments'] = int(accepted_match.group(1))
                        logger.info(f"Found accepted comments: {metadata['accepted_comments']}")
                        break
                
                # Pattern for total comments
                total_patterns = [
                    r'(\d+)\s+-\s+Όλα\s+τα\s+Σχόλια',
                    r'(\d+)\s+-\s+Όλα\s+τα\s+σχόλια',
                    r'(\d+)\s+σχόλια\s+συνολικά',
                    r'(\d+)\s+Σχόλια\s+συνολικά',
                    r'συνολικά\s+(\d+)\s+σχόλια'
                ]
                
                for pattern in total_patterns:
                    total_match = re.search(pattern, spot_text)
                    if total_match:
                        metadata['total_comments'] = int(total_match.group(1))
                        logger.info(f"Found total comments: {metadata['total_comments']}")
                        break
            
            # As a fallback, if we have accepted comments but no total, use accepted as total
            if metadata['accepted_comments'] > 0 and metadata['total_comments'] == 0:
                metadata['total_comments'] = metadata['accepted_comments']
                logger.info(f"Using accepted comments as total: {metadata['total_comments']}")
                
            # Check comment links to try another approach if needed
            if metadata['total_comments'] == 0:
                comment_links = soup.find_all('a', href=re.compile(r'allcomments'))
                for link in comment_links:
                    link_text = link.get_text()
                    total_match = re.search(r'(\d+)', link_text)
                    if total_match:
                        metadata['total_comments'] = int(total_match.group(1))
                        logger.info(f"Found total comments from link: {metadata['total_comments']}")
                        break
        except Exception as e:
            logger.error(f"Error extracting comment statistics: {e}")
        
        # 5. Get title and minister messages
        try:
            post_div = soup.find('div', class_='post clearfix')
            if post_div:
                # Get title with multiple fallbacks
                title_element = post_div.find('h3')
                if title_element:
                    metadata['title'] = title_element.get_text(strip=True)
                    logger.info(f"Found title: {metadata['title']}")
                else:
                    # Try other common title elements
                    for tag in ['h1', 'h2', 'h4', 'strong']:
                        alt_title = post_div.find(tag)
                        if alt_title:
                            metadata['title'] = alt_title.get_text(strip=True)
                            logger.info(f"Found title using alternate tag {tag}: {metadata['title']}")
                            break
                
                # If no title found, construct it from post_id
                if not metadata['title'] and metadata['post_id']:
                    metadata['title'] = f"Δημόσια Διαβούλευση Υπουργείου Δικαιοσύνης {metadata['post_id']}"
                    logger.info(f"Created default title from post_id: {metadata['title']}")
                
                # Get end minister message (for finished deliberations)
                end_message_div = post_div.find('div', class_='post_content is_complete')
                if end_message_div:
                    metadata['end_minister_message'] = extract_content_text(end_message_div)
                    logger.info(f"Found end minister message: {len(metadata['end_minister_message'])} chars")
                
                # Get start minister message
                # First approach: Find divs with just class='post_content' and not 'is_complete'
                all_content_divs = post_div.find_all('div', class_='post_content')
                
                for div in all_content_divs:
                    # Skip the end message div if we already found it
                    if div == end_message_div:
                        continue
                        
                    # Check if this div has 'post_content' without 'is_complete'
                    classes = div.get('class', [])
                    if 'post_content' in classes and 'is_complete' not in classes:
                        metadata['start_minister_message'] = extract_content_text(div)
                        if metadata['start_minister_message']:
                            logger.info(f"Found start minister message: {len(metadata['start_minister_message'])} chars")
                            break
                
                # Fallback #1: If still no start message, try any content div that's not the end message
                if not metadata['start_minister_message'] and len(all_content_divs) > 1:
                    for div in all_content_divs:
                        if div == end_message_div:
                            continue
                        metadata['start_minister_message'] = extract_content_text(div)
                        if metadata['start_minister_message']:
                            logger.info(f"Found start minister message (fallback 1): {len(metadata['start_minister_message'])} chars")
                            break
                
                # Fallback #2: Look at the first substantial paragraph in the post div
                if not metadata['start_minister_message']:
                    paragraphs = post_div.find_all('p')
                    for p in paragraphs:
                        text = p.get_text(strip=True)
                        if len(text) > 100:  # Must be a substantial paragraph
                            metadata['start_minister_message'] = text
                            logger.info(f"Found start minister message (fallback 2): {len(metadata['start_minister_message'])} chars")
                            break
        except Exception as e:
            logger.error(f"Error extracting title and minister messages: {e}")
        
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
            if key != 'start_minister_message' and key != 'end_minister_message':
                print(f"{key}: {value}")
        
        print("\nMinistry Info:")
        for key, value in result['ministry'].items():
            print(f"{key}: {value}")
        
        print("\nDocuments:")
        for doc in result['documents']:
            print(f"- {doc['title']} ({doc['type']}): {doc['url']}")
        
        print(f"\nStart Minister Message Length: {len(result['consultation']['start_minister_message'])} chars")
        print(f"End Minister Message Length: {len(result['consultation']['end_minister_message'])} chars")
