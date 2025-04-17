#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import logging
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import urllib.parse
import time
from random import uniform

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
        
        # Parse the date string
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
    
    # If no paragraphs found, get all text
    if not paragraphs:
        return element.get_text(strip=True)
    
    return "\n\n".join(text_parts)

def extract_article_links(url):
    """Extract article links from a consultation page"""
    try:
        # Fetch the HTML content
        logger.info(f"Fetching article list from URL: {url}")
        headers = {
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        
        # Parse HTML
        soup = BeautifulSoup(response.content, 'html.parser')
        
        articles = []
        
        # Method 1: Find the navigation div with article links (approach from bs4_article_scraper.py)
        consnav_div = soup.find('div', id='consnav')
        if not consnav_div:
            logger.warning("Could not find div with id='consnav'")
            # Try alternate method - look for any nav container
            consnav_div = soup.find('div', class_='navigation')
        
        if consnav_div:
            # Find the articles list
            articles_list = consnav_div.find('ul', class_='other_posts')
            if not articles_list:
                # Try alternate list classes
                articles_list = consnav_div.find('ul', class_='articlesList')
            
            if articles_list:
                # Find all <li> elements in the articles list
                li_elements = articles_list.find_all('li')
                logger.info(f"Found {len(li_elements)} article links in navigation")
                
                # Extract the links from each <li> element
                for li in li_elements:
                    try:
                        # First try to find link with class="list_comments_link"
                        link = li.find('a', class_='list_comments_link')
                        link_type = "comments_link"
                        
                        # If not found, look for any link
                        if not link:
                            link = li.find('a')
                            link_type = "regular_link"
                        
                        if link and link.has_attr('href'):
                            article_url = urllib.parse.urljoin(url, link['href'])
                            article_title = link.get_text(strip=True)
                            
                            # Try to extract the post ID from the URL
                            post_id = None
                            if '?p=' in article_url:
                                post_id = article_url.split('?p=')[1].split('&')[0]
                            
                            articles.append({
                                'post_id': post_id,
                                'title': article_title,
                                'url': article_url
                            })
                            logger.info(f"Found article ({link_type}): {article_title}")
                    except Exception as e:
                        logger.error(f"Error processing article link: {e}")
        
        # Method 2: If no articles found yet, try looking for an articles list in the main content
        if not articles:
            # Try to find an articles list
            articles_div = soup.find('ul', class_='articlesList')
            if not articles_div:
                articles_div = soup.find('div', class_='articlesList')
            
            if articles_div:
                list_items = articles_div.find_all('li')
                logger.info(f"Found {len(list_items)} list items in articles div")
                
                for item in list_items:
                    link = item.find('a')
                    if link and link.has_attr('href'):
                        article_url = urllib.parse.urljoin(url, link['href'])
                        article_title = link.get_text(strip=True)
                        
                        # Try to extract the post ID from the URL
                        post_id = None
                        if '?p=' in article_url:
                            post_id = article_url.split('?p=')[1].split('&')[0]
                        
                        articles.append({
                            'post_id': post_id,
                            'title': article_title,
                            'url': article_url
                        })
                        logger.info(f"Found article (articles div): {article_title}")
        
        # Method 3: If still no articles, look in the post content area
        if not articles:
            # Look for links in the main content area that might be articles
            content_divs = soup.find_all('div', class_='post_content')
            
            for div in content_divs:
                links = div.find_all('a')
                
                for link in links:
                    # Check if this looks like an article link 
                    if link.has_attr('href') and '?p=' in link['href']:
                        article_url = urllib.parse.urljoin(url, link['href'])
                        article_title = link.get_text(strip=True)
                        
                        # Skip obvious non-article links
                        if len(article_title) < 3 or 'http' in article_title.lower():
                            continue
                            
                        post_id = article_url.split('?p=')[1].split('&')[0]
                        
                        articles.append({
                            'post_id': post_id,
                            'title': article_title,
                            'url': article_url
                        })
                        logger.info(f"Found article (content link): {article_title}")
        
        return articles
    except Exception as e:
        logger.error(f"Error extracting article links: {e}")
        return []

def scrape_article_content(article_url):
    """Scrape article content and comments"""
    try:
        # Fetch the HTML content
        logger.info(f"Fetching article from URL: {article_url}")
        headers = {
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        response = requests.get(article_url, headers=headers, timeout=30)
        response.raise_for_status()
        
        # Parse HTML
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Extract article info
        article_info = {
            'post_id': None,
            'title': '',
            'content': '',
            'url': article_url,
            'comments': []
        }
        
        # Get post ID from URL
        if '?p=' in article_url:
            article_info['post_id'] = article_url.split('?p=')[1].split('&')[0]
        
        # Get article title
        title_element = soup.find('h3', class_='blogpost-title')
        if not title_element:
            title_element = soup.find('h3')  # Fallback to any h3
        
        if title_element:
            article_info['title'] = title_element.get_text(strip=True)
            logger.info(f"Article title: {article_info['title']}")
        
        # Get article content
        content_div = soup.find('div', class_='post_content')
        if content_div:
            article_info['content'] = extract_content_text(content_div)
            logger.info(f"Article content extracted: {len(article_info['content'])} chars")
        
        # Extract comments
        article_info['comments'] = extract_comments(soup, article_url)
        logger.info(f"Extracted {len(article_info['comments'])} comments")
        
        return article_info
    except Exception as e:
        logger.error(f"Error scraping article content: {e}")
        return None

def extract_comments(soup, article_url):
    """Extract comments from the article page"""
    comments = []
    
    try:
        # Find the comments section - try different selectors for different page structures
        comments_div = soup.find('div', id='comments')
        if not comments_div:
            # Try alternative selectors
            for selector in ['div.comments-template', 'div.comments_template', 'div.comments-area', 'div.comments']:
                comments_div = soup.select_one(selector)
                if comments_div:
                    logger.info(f"Found comments div with selector: {selector}")
                    break
        
        if not comments_div:
            logger.warning("No comments section found")
            return comments
        
        # Find the comment list container (ul or ol with class='comment_list')
        comment_list = None
        for selector in ['ol.comment_list', 'ul.comment_list', 'ol.commentlist', 'ul.commentlist']:
            comment_list = comments_div.select_one(selector)
            if comment_list:
                logger.info(f"Found comment list with selector: {selector}")
                break
        
        if not comment_list:
            logger.warning("No comment list found")
            return comments
        
        # Find all elements with class="author" - these contain the username and date information
        author_divs = comment_list.find_all('div', class_='author')
        logger.info(f"Found {len(author_divs)} author divs")
        
        # Find all <li> elements with id starting with "comment-"
        comment_items = []
        for li in comment_list.find_all('li'):
            if li.get('id') and li.get('id').startswith('comment-'):
                comment_items.append(li)
        
        logger.info(f"Found {len(comment_items)} comment items with id starting with 'comment-'")
        
        # Process comments with IDs
        if comment_items:
            for item in comment_items:
                try:
                    # Extract comment ID
                    comment_id = item['id'].replace('comment-', '')
                    
                    # Extract username and date from author div
                    username = "Anonymous"
                    date_obj = None
                    
                    # Find author div within this comment
                    author_div = item.find('div', class_='author')
                    
                    if author_div:
                        author_html = str(author_div)
                        author_text = author_div.get_text(strip=True)
                        
                        # Try to extract username using a more robust approach
                        # First check if there's a <strong> tag for the username
                        strong_tag = author_div.find('strong')
                        if strong_tag:
                            username = strong_tag.get_text(strip=True)
                        else:
                            # Try parsing from full text with different separators
                            separators = ['|', '–', '-', '—']
                            for separator in separators:
                                if separator in author_text:
                                    parts = author_text.split(separator, 1)
                                    if len(parts) >= 2:
                                        potential_username = parts[0].strip()
                                        if potential_username and len(potential_username) < 50:  # Reasonable username length
                                            username = potential_username
                                            date_str = parts[1].strip()
                                            date_obj = parse_greek_date(date_str)
                                            break
                    
                    # Extract comment content
                    p_elements = item.find_all('p')
                    content = "\n\n".join([p.get_text(strip=True) for p in p_elements if p.get_text(strip=True)])
                    
                    # If no paragraphs found or content is empty, try alternate approach
                    if not content and author_div:
                        # Get text content excluding the author div
                        content = item.get_text(strip=True).replace(author_div.get_text(strip=True), '').strip()
                    
                    if content:  # Only add if we have actual content
                        comments.append({
                            'comment_id': comment_id,
                            'username': username,
                            'date': date_obj,
                            'content': content
                        })
                        logger.info(f"Extracted comment ID {comment_id} by {username}")
                except Exception as e:
                    logger.error(f"Error processing comment item: {e}")
        
        # If no comments found using the ID method, try the paragraph method
        if not comments:
            # Find all paragraphs directly under the comment list
            p_elements = comment_list.find_all('p', recursive=False)
            logger.info(f"Found {len(p_elements)} paragraph elements directly under comment_list")
            
            # Process each paragraph as a comment
            for i, p in enumerate(p_elements):
                try:
                    content = p.get_text(strip=True)
                    if not content:  # Skip empty paragraphs
                        continue
                        
                    # Try to extract username/date from author divs if available
                    username = "Anonymous"
                    date_obj = None
                    
                    if i < len(author_divs):
                        author_div = author_divs[i]
                        if author_div:
                            author_text = author_div.get_text(strip=True)
                            
                            # Try multiple separators to extract username and date
                            separators = ['|', '–', '-', '—']
                            for separator in separators:
                                if separator in author_text:
                                    parts = author_text.split(separator, 1)
                                    if len(parts) >= 2:
                                        username = parts[0].strip()
                                        date_str = parts[1].strip()
                                        date_obj = parse_greek_date(date_str)
                                        break
                    
                    # Add the comment
                    comments.append({
                        'comment_id': f"comment-{i+1}",
                        'username': username,
                        'date': date_obj,
                        'content': content
                    })
                    logger.info(f"Extracted comment (paragraph method) by {username}")
                except Exception as e:
                    logger.error(f"Error processing comment paragraph: {e}")
        
        return comments
    except Exception as e:
        logger.error(f"Error extracting comments: {e}")
        return comments

def scrape_consultation_content(consultation_url, delay_range=(0.5, 1.5)):
    """Scrape all articles and comments from a consultation"""
    try:
        # Get all article links
        articles_links = extract_article_links(consultation_url)
        logger.info(f"Found {len(articles_links)} article links")
        
        # Scrape each article
        articles_content = []
        for i, article in enumerate(articles_links):
            # Introduce a small delay between requests to avoid overloading the server
            if i > 0:
                delay = uniform(*delay_range)
                logger.info(f"Waiting {delay:.2f} seconds before next request...")
                time.sleep(delay)
            
            article_data = scrape_article_content(article['url'])
            if article_data:
                articles_content.append(article_data)
        
        logger.info(f"Successfully scraped {len(articles_content)} articles")
        
        # Count total comments
        total_comments = sum(len(article['comments']) for article in articles_content)
        logger.info(f"Total comments across all articles: {total_comments}")
        
        return articles_content
    except Exception as e:
        logger.error(f"Error scraping consultation content: {e}")
        return []

if __name__ == "__main__":
    # Example usage
    test_url = "http://www.opengov.gr/ministryofjustice/?p=17805"
    articles = scrape_consultation_content(test_url)
    
    if articles:
        print(f"\nScraped {len(articles)} articles with a total of {sum(len(a['comments']) for a in articles)} comments")
        for i, article in enumerate(articles[:3]):  # Print details for first 3 articles
            print(f"\nArticle {i+1}: {article['title']}")
            print(f"  ID: {article['post_id']}")
            print(f"  URL: {article['url']}")
            print(f"  Content length: {len(article['content'])} chars")
            print(f"  Comments: {len(article['comments'])}")
            
            # Print first 2 comments if any
            for j, comment in enumerate(article['comments'][:2]):
                print(f"    Comment {j+1}: {comment['username']} ({comment['date']})")
                print(f"      Content: {comment['content'][:100]}...")
        
        print("\n(Showing only first 3 articles and 2 comments per article)")
