#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import os
import csv
import logging
import requests
from bs4 import BeautifulSoup
import urllib.parse

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def get_article_links(soup):
    """Extract article links from the navigation list using BeautifulSoup"""
    article_links = []
    
    # Find the navigation div
    consnav_div = soup.find('div', id='consnav')
    if not consnav_div:
        logger.warning("Could not find div with id='consnav'")
        return article_links
    
    # Find the articles list
    articles_list = consnav_div.find('ul', class_='other_posts')
    if not articles_list:
        logger.warning("Could not find ul with class='other_posts'")
        return article_links
    
    # Find all <li> elements in the articles list
    li_elements = articles_list.find_all('li')
    logger.info(f"Found {len(li_elements)} article links")
    
    # Extract the links from each <li> element
    for li in li_elements:
        try:
            # First try to find link with class="list_comments_link"
            link = li.find('a', class_='list_comments_link')
            link_type = "comments_link"
            
            # Fall back to any link in the list item
            if not link:
                links = li.find_all('a')
                if links:
                    link = links[0]  # Take the first link
                    link_type = "other_link"
                else:
                    logger.warning("No links found in list item")
                    continue
            
            # Extract URL and title
            article_url = link.get('href')
            article_title = link.get('title') or link.text
            
            logger.info(f"Found article: {article_title} at {article_url} (link type: {link_type})")
            article_links.append((article_url, article_title))
        except Exception as e:
            logger.warning(f"Error extracting article link: {str(e)}")
    
    return article_links

def get_article_content(soup):
    """Extract article content using BeautifulSoup"""
    # Find the content div
    content_div = soup.find('div', class_='post clearfix')
    if not content_div:
        logger.warning("Could not find div with class='post clearfix'")
        return "Unknown Title", ""
    
    # Extract title
    try:
        title_element = content_div.find('h3')
        title = title_element.text.strip()
        logger.info(f"Found title: {title}")
    except:
        title = "Unknown Title"
        logger.warning("Could not find h3 title element")
    
    # Extract content
    try:
        content_element = content_div.find('div', class_='post_content')
        
        # Initialize content parts list
        content_parts = []
        
        # Get text from paragraphs
        paragraphs = content_element.find_all('p')
        for p in paragraphs:
            content_parts.append(p.text.strip())
        
        # Get text from ordered lists
        ol_elements = content_element.find_all('ol')
        for ol in ol_elements:
            li_elements = ol.find_all('li')
            for i, li in enumerate(li_elements, 1):
                content_parts.append(f"{i}. {li.text.strip()}")
        
        # Get text from unordered lists
        ul_elements = content_element.find_all('ul')
        for ul in ul_elements:
            li_elements = ul.find_all('li')
            for li in li_elements:
                content_parts.append(f"• {li.text.strip()}")
        
        content = "\n\n".join(content_parts)
        logger.info(f"Found content with {len(paragraphs)} paragraphs")
    except:
        content = ""
        logger.warning("Could not find content element")
    
    return title, content

def get_article_comments(soup):
    """Extract article comments using BeautifulSoup"""
    comments = []
    
    # Find the comments div
    comments_div = soup.find('div', id='comments')
    if not comments_div:
        logger.warning("Could not find div with id='comments'")
        return comments
    
    # Look for the comment list - try different possible selectors
    comment_list = None
    for selector in ['ol.comment_list', 'ul.comment_list']:
        comment_list = comments_div.select_one(selector)
        if comment_list:
            logger.info(f"Found comment list with {selector} selector")
            break
    
    if not comment_list:
        logger.warning("No comment list found")
        return comments
    
    # Find all elements with class="author" - these contain the author and date information
    author_divs = comment_list.find_all('div', class_='author')
    logger.info(f"Found {len(author_divs)} author divs")
    
    # Find all <li> elements with id starting with "comment-"
    # BeautifulSoup equivalent of XPath: ".//li[starts-with(@id, 'comment-')]"
    comment_items = []
    for li in comment_list.find_all('li'):
        if li.get('id') and li.get('id').startswith('comment-'):
            comment_items.append(li)
    
    logger.info(f"Found {len(comment_items)} comment items with id starting with 'comment-'")
    
    # If we couldn't find comment items with IDs, fall back to using paragraph elements
    if not comment_items:
        # Find all comment paragraphs directly under the comment list
        # BeautifulSoup equivalent of XPath: "./p"
        p_elements = comment_list.find_all('p', recursive=False)  # Only direct children
        logger.info(f"Found {len(p_elements)} paragraph elements directly under comment_list")
        
        # Make sure we have the correct number of paragraphs (should match the site's count)
        if len(p_elements) != len(author_divs) and len(author_divs) > 0:
            logger.warning(f"Mismatch between paragraph count ({len(p_elements)}) and author count ({len(author_divs)})")
        
        # Extract comment content and author info
        for i, p in enumerate(p_elements):
            if p.text.strip():  # Skip empty paragraphs
                # Get author/date info if available
                author_text = "Anonymous"
                date_text = "Unknown date"
                
                if i < len(author_divs):
                    try:
                        author_div = author_divs[i]
                        author_html = str(author_div)
                        
                        # Parse the HTML to extract date and author
                        date_match = re.search(r'([^|]+)\|', author_html)
                        if date_match:
                            date_text = date_match.group(1).strip()
                        
                        # Extract author (text inside <strong> tags)
                        author_match = re.search(r'<strong>([^<]+)</strong>', author_html)
                        if author_match:
                            author_text = author_match.group(1).strip()
                    except Exception as e:
                        logger.error(f"Error extracting author/date: {e}")
                
                comments.append({
                    "content": p.text.strip(),
                    "author": author_text,
                    "date": date_text
                })
                logger.info(f"Comment extracted: {p.text[:50]}... by {author_text} on {date_text}")
    else:
        # Process comments using the comment items with IDs
        for i, item in enumerate(comment_items):
            # Find the paragraph with the comment content
            p_elements = item.find_all('p')
            if not p_elements:
                continue
            
            content = "\n".join([p.text.strip() for p in p_elements if p.text.strip()])
            
            # Get author/date info if available
            author_text = "Anonymous"
            date_text = "Unknown date"
            
            # Find author div within this comment item
            item_author_divs = item.find_all('div', class_='author')
            if item_author_divs:
                try:
                    author_div = item_author_divs[0]
                    author_html = str(author_div)
                    
                    # Parse the HTML to extract date and author
                    date_match = re.search(r'([^|]+)\|', author_html)
                    if date_match:
                        date_text = date_match.group(1).strip()
                    
                    # Extract author (text inside <strong> tags)
                    author_match = re.search(r'<strong>([^<]+)</strong>', author_html)
                    if author_match:
                        author_text = author_match.group(1).strip()
                except Exception as e:
                    logger.error(f"Error extracting author/date: {e}")
            elif i < len(author_divs):
                # Fall back to the author divs we found earlier
                try:
                    author_div = author_divs[i]
                    author_html = str(author_div)
                    
                    # Parse the HTML to extract date and author
                    date_match = re.search(r'([^|]+)\|', author_html)
                    if date_match:
                        date_text = date_match.group(1).strip()
                    
                    # Extract author (text inside <strong> tags)
                    author_match = re.search(r'<strong>([^<]+)</strong>', author_html)
                    if author_match:
                        author_text = author_match.group(1).strip()
                except Exception as e:
                    logger.error(f"Error extracting author/date: {e}")
            
            comments.append({
                "content": content,
                "author": author_text,
                "date": date_text
            })
            logger.info(f"Comment extracted: {content[:50]}... by {author_text} on {date_text}")
    
    return comments

def save_articles_to_files(articles_data, articles_text_file="articles_content.txt", articles_csv_file="articles_data.csv"):
    """Save extracted articles to text and CSV files"""
    # Save articles to text file
    with open(articles_text_file, 'w', encoding='utf-8') as f:
        for article in articles_data:
            f.write(f"Title: {article['title']}\n")
            f.write("="*80 + "\n")
            f.write(f"{article['content']}\n\n")
            
            f.write("Comments:\n")
            f.write("-"*80 + "\n")
            for comment in article['comments']:
                f.write(f"Author: {comment['author']} | Date: {comment['date']}\n")
                f.write(f"{comment['content']}\n")
                f.write("-"*40 + "\n")
            
            f.write("\n\n" + "="*80 + "\n\n")
    
    # Save articles to CSV file
    with open(articles_csv_file, 'w', newline='', encoding='utf-8') as f:
        fieldnames = ['article_title', 'article_url', 'article_content', 'comment_count']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        
        for article in articles_data:
            writer.writerow({
                'article_title': article['title'],
                'article_url': article['url'],
                'article_content': article['content'][:200] + '...' if len(article['content']) > 200 else article['content'],
                'comment_count': len(article['comments'])
            })
    
    logger.info(f"Saved {len(articles_data)} articles to {articles_text_file} and {articles_csv_file}")

def scrape_legislation(legislation_url):
    """Scrape a legislation's articles and comments"""
    logger.info(f"Scraping legislation at {legislation_url}")
    
    # Prepare list to store article data
    articles_data = []
    
    # Fetch the legislation landing page
    headers = {
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    try:
        response = requests.get(legislation_url, headers=headers, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Get all article links
        article_links = get_article_links(soup)
        
        # Process each article
        for article_url, article_title in article_links:
            logger.info(f"Processing article: {article_title}")
            
            # Fetch the article page
            article_response = requests.get(article_url, headers=headers, timeout=30)
            article_response.raise_for_status()
            article_soup = BeautifulSoup(article_response.content, 'html.parser')
            
            # Extract article content
            title, content = get_article_content(article_soup)
            
            # Extract article comments
            comments = get_article_comments(article_soup)
            
            # Store article data
            articles_data.append({
                'title': title,
                'url': article_url,
                'content': content,
                'comments': comments
            })
            
            logger.info(f"Extracted article with {len(comments)} comments")
    
    except Exception as e:
        logger.error(f"Error scraping legislation: {e}")
    
    # Save article data to files
    if articles_data:
        save_articles_to_files(articles_data)
    
    return articles_data

def main():
    """Main function"""
    # Example legislation URL
    legislation_url = "https://www.opengov.gr/ministryofjustice/?p=17777"
    
    # Scrape the legislation
    articles_data = scrape_legislation(legislation_url)
    
    # Print summary
    logger.info(f"Scraped {len(articles_data)} articles")
    total_comments = sum(len(article['comments']) for article in articles_data)
    logger.info(f"Total comments: {total_comments}")

if __name__ == "__main__":
    main()
