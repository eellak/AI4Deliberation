#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import logging
import urllib.parse
import unicodedata
from datetime import datetime
from bs4 import BeautifulSoup

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
        
        # Remove extra spaces and standardize format
        date_string = re.sub(r'\s+', ' ', date_string).strip()
        
        # Parse the date string with different possible formats
        if ',' in date_string:
            return datetime.strptime(date_string, '%d %B %Y, %H:%M')
        else:
            return datetime.strptime(date_string, '%d %B %Y')
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
    
    # If no paragraphs or lists found, get all text
    if not text_parts:
        return element.get_text(strip=True)
    
    return "\n\n".join(text_parts)

def find_element_with_fallbacks(soup, selectors):
    """Find an element using a list of CSS selectors, trying each in order"""
    for selector in selectors:
        element = soup.select_one(selector)
        if element:
            logger.info(f"Found element with selector: {selector}")
            return element
    return None

def extract_post_id(url):
    """Extract the post ID from a URL"""
    try:
        if '?p=' in url:
            return url.split('?p=')[1].split('&')[0]
        return None
    except Exception:
        return None

def build_absolute_url(base_url, relative_url):
    """Build an absolute URL from a base URL and a relative URL"""
    return urllib.parse.urljoin(base_url, relative_url)

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

def get_request_headers():
    """Return headers for HTTP requests"""
    return {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept-Language': 'el-GR,el;q=0.9,en-US;q=0.8,en;q=0.7'
    }

def normalize_text(text):
    """
    Normalizes text by:
    1. Removing accents
    2. Converting to UPPERCASE
    
    Args:
        text: Original text
    
    Returns:
        Normalized text
    """
    if not text:
        return ""
    
    # Remove accents
    normalized = unicodedata.normalize('NFKD', text)
    normalized = ''.join([c for c in normalized if not unicodedata.combining(c)])
    
    # Convert to uppercase
    normalized = normalized.upper()
    
    return normalized


def categorize_document(title):
    """
    Categorizes a document based on its normalized title.
    
    Args:
        title: Document title
        
    Returns:
        Document type: 'law_draft', 'analysis', 'deliberation_report', 'other_draft',
        'other_report', or 'other'
    """
    # Normalize the title
    normalized_title = normalize_text(title)
    
    # Check for law draft - look for both words separately
    if 'ΣΧΕΔΙΟ' in normalized_title and 'ΝΟΜΟΥ' in normalized_title:
        return 'law_draft'
    
    # Check for analysis - look for both words separately
    if 'ΑΝΑΛΥΣΗ' in normalized_title and 'ΣΥΝΕΠΕΙΩΝ' in normalized_title:
        return 'analysis'
    
    # Check for deliberation report - this was already looking for both words
    if 'ΕΚΘΕΣΗ' in normalized_title and 'ΔΙΑΒΟΥΛΕΥΣΗ' in normalized_title:
        return 'deliberation_report'
    
    # Check for non-law draft documents (only if none of the above matched)
    # These are documents that contain ΣΧΕΔΙΟ but not ΝΟΜΟΥ
    if 'ΣΧΕΔΙΟ' in normalized_title and 'ΝΟΜΟΥ' not in normalized_title:
        return 'other_draft'
    
    # Check for general reports (only if none of the above matched)
    # These are documents that contain ΕΚΘΕΣΗ but not ΔΙΑΒΟΥΛΕΥΣΗ
    if 'ΕΚΘΕΣΗ' in normalized_title and 'ΔΙΑΒΟΥΛΕΥΣΗ' not in normalized_title:
        return 'other_report'
        
    # Default to 'other'
    return 'other'
