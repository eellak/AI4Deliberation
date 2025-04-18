#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import requests
from bs4 import BeautifulSoup
import urllib.parse
import time
from random import uniform

# Import utilities from shared module
from utils import (
    parse_greek_date, 
    extract_content_text, 
    find_element_with_fallbacks,
    extract_post_id, 
    build_absolute_url,
    get_request_headers
)

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def extract_article_links(url):
    """Extract article links from a consultation page using a simplified approach"""
    try:
        # Fetch the HTML content
        logger.info(f"Fetching article list from URL: {url}")
        response = requests.get(url, headers=get_request_headers(), timeout=30, allow_redirects=True)
        response.raise_for_status()
        
        # Get the final URL after any redirections
        final_url = response.url
        if final_url != url:
            logger.info(f"URL was redirected: {url} -> {final_url}")
            url = final_url
        
        # Parse HTML
        soup = BeautifulSoup(response.content, 'html.parser')
        
        articles = []
        
        # Primary method: Find the navigation div with article links
        # This is based on the approach from bs4_article_scraper.py
        nav_selectors = ['div#consnav', 'div.navigation']
        consnav_div = find_element_with_fallbacks(soup, nav_selectors)
        
        if consnav_div:
            # Find the articles list with fallbacks
            list_selectors = ['ul.other_posts', 'ul.articlesList']
            articles_list = find_element_with_fallbacks(consnav_div, list_selectors)
            
            if articles_list:
                # Find all <li> elements in the articles list
                li_elements = articles_list.find_all('li')
                logger.info(f"Found {len(li_elements)} article links in navigation")
                
                # Extract the links from each <li> element
                for li in li_elements:
                    try:
                        # Try to find link (with fallback)
                        link = li.find('a', class_='list_comments_link') or li.find('a')
                        
                        if link and link.has_attr('href'):
                            article_url = build_absolute_url(url, link['href'])
                            article_title = link.get_text(strip=True)
                            post_id = extract_post_id(article_url)
                            
                            articles.append({
                                'post_id': post_id,
                                'title': article_title,
                                'url': article_url
                            })
                            logger.info(f"Found article: {article_title}")
                    except Exception as e:
                        logger.error(f"Error processing article link: {e}")
        
        # Fallback method: If no articles found, look for links in content area
        if not articles:
            logger.info("No articles found in navigation, trying content area")
            content_divs = soup.find_all('div', class_='post_content')
            
            for div in content_divs:
                links = div.find_all('a')
                
                for link in links:
                    # Check if this looks like an article link
                    if link.has_attr('href') and '?p=' in link['href']:
                        article_url = build_absolute_url(url, link['href'])
                        article_title = link.get_text(strip=True)
                        
                        # Skip obvious non-article links
                        if len(article_title) < 3 or 'http' in article_title.lower():
                            continue
                            
                        post_id = extract_post_id(article_url)
                        
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
    """Scrape article content and comments using a simplified approach"""
    try:
        # Fetch the HTML content
        logger.info(f"Fetching article from URL: {article_url}")
        response = requests.get(article_url, headers=get_request_headers(), timeout=30, allow_redirects=True)
        response.raise_for_status()
        
        # Get the final URL after any redirections
        final_url = response.url
        if final_url != article_url:
            logger.info(f"URL was redirected: {article_url} -> {final_url}")
            article_url = final_url
        
        # Parse HTML
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Initialize article info structure
        article_info = {
            'post_id': extract_post_id(article_url),  # Now using the final URL after redirects
            'title': '',
            'content': '',
            'url': article_url,  # This is now the final URL after redirects
            'comments': []
        }
        
        # Get article title - try specific class first, then any h3
        title_selectors = ['h3.blogpost-title', 'h3']
        title_element = find_element_with_fallbacks(soup, title_selectors)
        
        if title_element:
            article_info['title'] = title_element.get_text(strip=True)
            logger.info(f"Article title: {article_info['title']}")
        
        # Get article content
        content_div = soup.find('div', class_='post_content')
        if content_div:
            # Store the raw HTML content
            article_info['raw_html'] = str(content_div)
            logger.info(f"Raw HTML content captured: {len(article_info['raw_html'])} chars")
            
            # Store the formatted content text
            article_info['content'] = extract_content_text(content_div)
            logger.info(f"Formatted content extracted: {len(article_info['content'])} chars")
        
        # Extract comments
        article_info['comments'] = extract_comments(soup, article_url)
        logger.info(f"Extracted {len(article_info['comments'])} comments")
        
        return article_info
    except Exception as e:
        logger.error(f"Error scraping article content: {e}")
        return None

def extract_comments(soup, article_url):
    """Extract comments from the article page with a simplified approach"""
    comments = []
    
    try:
        # Find the comments section with fallback selectors
        comment_section_selectors = ['div#comments', 'div.comments-template', 'div.comments_template', 'div.comments-area', 'div.comments']
        comments_div = find_element_with_fallbacks(soup, comment_section_selectors)
        
        if not comments_div:
            logger.warning("No comments section found")
            return comments
        
        # Find the comment list container (ul or ol with class='comment_list')
        comment_list_selectors = ['ol.comment_list', 'ul.comment_list', 'ol.commentlist', 'ul.commentlist']
        comment_list = find_element_with_fallbacks(comments_div, comment_list_selectors)
        
        if not comment_list:
            logger.warning("No comment list found")
            return comments
        
        # Find all elements with class="author" - these contain the username and date information
        author_divs = comment_list.find_all('div', class_='author')
        logger.info(f"Found {len(author_divs)} author divs")
        
        # Primary method: Find and process comments with IDs
        comment_items = []
        for li in comment_list.find_all('li'):
            if li.get('id') and li.get('id').startswith('comment-'):
                comment_items.append(li)
        
        logger.info(f"Found {len(comment_items)} comment items with id starting with 'comment-'")
        
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
                        author_text = author_div.get_text(strip=True)
                        
                        # Try to extract date and username using regex first
                        import re
                        date_username_pattern = r'(\d+\s+[Α-Ωα-ωίϊΐόάέύϋΰήώ]+\s+\d{4},\s+\d{1,2}:\d{2})\s*\|\s*(.+)'
                        match = re.search(date_username_pattern, author_text)
                        
                        if match:
                            # Extract date
                            date_str = match.group(1).strip()
                            date_obj = parse_greek_date(date_str)
                            
                            # Extract username
                            username_part = match.group(2).strip()
                            # If there's a strong tag, use its contents instead as it's more reliable
                            strong_tag = author_div.find('strong')
                            if strong_tag:
                                username = strong_tag.get_text(strip=True)
                            else:
                                username = username_part
                            
                            logger.info(f"Extracted date: {date_str} and username: {username}")
                        else:
                            # Fallback: try to extract just the date with a simpler pattern
                            date_pattern = r'(\d+\s+[Α-Ωα-ωίϊΐόάέύϋΰήώ]+\s+\d{4},\s+\d{1,2}:\d{2})'
                            date_match = re.search(date_pattern, author_text)
                            
                            if date_match:
                                date_str = date_match.group(1).strip()
                                date_obj = parse_greek_date(date_str)
                                logger.info(f"Extracted date: {date_str}")
                            
                            # Try extracting username from strong tag
                            strong_tag = author_div.find('strong')
                            if strong_tag:
                                username = strong_tag.get_text(strip=True)
                                logger.info(f"Extracted username: {username}")
                            else:
                                # If no strong tag, try with separator approach
                                for separator in ['|', '–', '-', '—']:
                                    if separator in author_text:
                                        parts = author_text.split(separator, 1)
                                        if len(parts) >= 2:
                                            if not date_obj:  # If we don't have a date yet
                                                date_str = parts[0].strip()
                                                date_obj = parse_greek_date(date_str)
                                                username = parts[1].strip()
                                            else:  # We already have a date
                                                username = parts[1].strip()
                                            break
                    
                    # Extract comment content from paragraphs
                    content = extract_content_text(item) 
                    
                    # If extraction method returned empty content but we have author div
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
                        logger.info(f"Extracted comment ID {comment_id} by {username} from {date_obj if date_obj else 'unknown date'}")
                except Exception as e:
                    logger.error(f"Error processing comment item: {e}")
        
        # Fallback method: If no comments found, use paragraph method
        if not comments and author_divs:
            logger.info("No ID-based comments found, trying paragraph method")
            # Find all paragraphs directly under the comment list
            p_elements = comment_list.find_all('p', recursive=False)
            
            # Process each paragraph as a comment
            for i, p in enumerate(p_elements):
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
                        
                        # Use regex for date extraction
                        import re
                        date_pattern = r'(\d+\s+[Α-Ωα-ωίϊΐόάέύϋΰήώ]+\s+\d{4},\s+\d{1,2}:\d{2})'
                        date_match = re.search(date_pattern, author_text)
                        if date_match:
                            date_str = date_match.group(1)
                            date_obj = parse_greek_date(date_str)
                        
                        # Try to get username from strong tag
                        strong_tag = author_div.find('strong')
                        if strong_tag:
                            username = strong_tag.get_text(strip=True)
                        else:
                            # Try separator approach as fallback
                            for separator in ['|', '–', '-', '—']:
                                if separator in author_text:
                                    parts = author_text.split(separator, 1)
                                    if len(parts) >= 2:
                                        username = parts[1].strip()  # Username is usually after separator
                                        break
                
                # Add the comment
                comments.append({
                    'comment_id': f"comment-{i+1}",
                    'username': username,
                    'date': date_obj,
                    'content': content
                })
                logger.info(f"Extracted comment (paragraph method) by {username}")
        
        return comments
    except Exception as e:
        logger.error(f"Error extracting comments: {e}")
        return comments

def scrape_consultation_content(consultation_url, delay_range=(0.15, 0.25)):
    """Scrape all articles and comments from a consultation with a simplified approach"""
    try:
        # Get all article links
        articles_links = extract_article_links(consultation_url)
        logger.info(f"Found {len(articles_links)} article links")
        
        # Scrape each article with a small delay between requests
        articles_content = []
        for i, article in enumerate(articles_links):
            # Add delay after the first request
            if i > 0:
                delay = uniform(*delay_range)
                logger.info(f"Waiting {delay:.2f} seconds before next request...")
                time.sleep(delay)
            
            # Scrape the article content and comments
            article_data = scrape_article_content(article['url'])
            if article_data:
                articles_content.append(article_data)
        
        # Log summary information
        article_count = len(articles_content)
        comment_count = sum(len(article['comments']) for article in articles_content)
        logger.info(f"Successfully scraped {article_count} articles with {comment_count} total comments")
        
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
