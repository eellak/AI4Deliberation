#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
import pandas as pd
import gc
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.common.exceptions import WebDriverException
from tqdm import tqdm
import os

def setup_driver():
    """Set up and return a configured webdriver, trying Chrome first, then Firefox if Chrome fails."""
    # Try Chrome first
    try:
        print("Attempting to use Chrome browser in headless mode...")
        chrome_options = Options()
        # Running in headless mode for better stability
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=1920,1080")
        # Memory optimization arguments
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--disable-dev-tools")
        chrome_options.add_argument("--disable-popup-blocking")
        chrome_options.add_argument("--blink-settings=imagesEnabled=false")
        chrome_options.add_argument("--js-flags=--expose-gc")
        chrome_options.add_argument("--disable-infobars")
        chrome_options.add_argument("--disable-notifications")
        chrome_options.add_argument("--aggressive-cache-discard")
        chrome_options.add_argument("--disable-cache")
        chrome_options.add_argument("--disable-application-cache")
        chrome_options.add_argument("--disable-offline-load-stale-cache")
        chrome_options.add_argument("--disk-cache-size=0")
        
        # Let Selenium find the appropriate driver
        driver = webdriver.Chrome(options=chrome_options)
        print("Successfully created Chrome webdriver")
        return driver
    except WebDriverException as e:
        print(f"Chrome webdriver setup failed: {e}")
        
        # Try Firefox as fallback
        try:
            print("Attempting to use Firefox browser in headless mode...")
            firefox_options = FirefoxOptions()
            # Running in headless mode for better stability
            firefox_options.add_argument("--headless")
            
            # Let Selenium find the appropriate driver
            driver = webdriver.Firefox(options=firefox_options)
            print("Successfully created Firefox webdriver")
            return driver
        except WebDriverException as e:
            print(f"Firefox webdriver setup failed: {e}")
            raise Exception("Could not initialize any webdriver. Please make sure Chrome or Firefox is installed.")

def click_search_button(driver):
    """Click the search button to display results."""
    try:
        search_button = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, ".buttons.lfilter-submit"))
        )
        search_button.click()
        # Wait for results to load
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.ID, "listing-items"))
        )
    except Exception as e:
        print(f"Error clicking search button: {e}")
        raise

def extract_table_data(driver):
    """Extract data from the current page of results."""
    table = driver.find_element(By.ID, "listing-items")
    rows = table.find_element(By.TAG_NAME, "tbody").find_elements(By.TAG_NAME, "tr")
    
    page_data = []
    for row in rows:
        cells = row.find_elements(By.TAG_NAME, "td")
        if len(cells) < 7:
            continue
        
        # Extract data from each cell
        law_type = cells[0].text.strip() if cells[0].text else ""
        law_number = cells[1].text.strip() if cells[1].text else ""
        description = cells[2].text.strip() if cells[2].text else ""
        
        # Extract FEK title and link
        fek_title = ""
        fek_url = ""
        if cells[3].find_elements(By.TAG_NAME, "a"):
            fek_element = cells[3].find_element(By.TAG_NAME, "a")
            fek_title = fek_element.text.strip() if fek_element.text else ""
            fek_url = fek_element.get_attribute("href") if fek_element.get_attribute("href") else ""
        
        date = cells[4].text.strip() if cells[4].text else ""
        pages = cells[5].text.strip() if cells[5].text else ""
        
        # Extract PDF download URL
        pdf_url = ""
        if cells[6].find_elements(By.CSS_SELECTOR, "a.table-link"):
            pdf_element = cells[6].find_element(By.CSS_SELECTOR, "a.table-link")
            pdf_url = pdf_element.get_attribute("href") if pdf_element.get_attribute("href") else ""
        
        # Create a dictionary for the row data
        row_data = {
            "law_type": law_type,
            "law_number": law_number,
            "description": description,
            "fek_title": fek_title,
            "fek_url": fek_url,
            "date": date,
            "pages": pages,
            "pdf_url": pdf_url
        }
        page_data.append(row_data)
    
    return page_data

def has_next_page(driver):
    """Check if there is a next page of results."""
    next_buttons = driver.find_elements(By.CSS_SELECTOR, "button.table-button[aria-label='Επόμενη']")
    if not next_buttons:
        return False
    
    # Check if the next button is disabled
    return "disabled" not in next_buttons[0].get_attribute("outerHTML")

def click_next_page(driver):
    """Click the button to navigate to the next page."""
    try:
        next_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "button.table-button[aria-label='Επόμενη']"))
        )
        next_button.click()
        # Wait for results to reload
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.ID, "listing-items"))
        )
        # Add a small delay to ensure the page is fully loaded
        time.sleep(2)
        return True
    except Exception as e:
        print(f"Error navigating to next page: {e}")
        return False

def get_current_page_number(driver):
    """Extract the current page number from the pagination indicator"""
    try:
        page_indicator = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "button.table-button.no-click"))
        )
        # Extract the page number from text like "Σελίδα 9 από 1721"
        text = page_indicator.text
        if "από" in text:
            # Extract the number before "από"
            current_page = int(text.split("από")[0].strip().split()[-1])
            total_pages = int(text.split("από")[1].strip())
            return current_page, total_pages
        return None, None
    except Exception as e:
        print(f"Error getting current page number: {e}")
        return None, None

def navigate_to_start_page(driver, target_page):
    """Rapidly click through pages until reaching the target page"""
    if target_page <= 1:
        return True
    
    # Get the current page
    current_page, total_pages = get_current_page_number(driver)
    if not current_page:
        print("Could not determine current page number, starting from page 1")
        current_page = 1
    
    print(f"Currently at page {current_page}, navigating to page {target_page}")
    
    # Click 'Next' button until we reach the target page
    while current_page < target_page:
        try:
            # Click the next button
            next_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "button.table-button[aria-label='Επόμενη']"))
            )
            next_button.click()
            
            # Wait for the page to load
            WebDriverWait(driver, 10).until(
                EC.staleness_of(next_button)
            )
            
            # Get the updated page number
            new_page, _ = get_current_page_number(driver)
            if new_page:
                if new_page > current_page:
                    print(f"Advanced to page {new_page}")
                    current_page = new_page
                else:
                    print(f"Warning: Page number did not increase: {current_page} -> {new_page}")
                    current_page = new_page
            else:
                print("Could not determine new page number, continuing...")
                current_page += 1
                
            # Brief pause to avoid overwhelming the server
            time.sleep(0.5)
            
        except Exception as e:
            print(f"Error navigating to page {target_page}: {e}")
            return False
    
    print(f"Successfully navigated to start page {target_page}")
    return True

def main(max_pages=None, start_page=1):
    url = "https://search.et.gr/el/search-legislation/?legislationCatalogues=1"
    output_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gazette_data.parquet")
    checkpoint_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "checkpoint.parquet")
    
    # Create output directory if it doesn't exist
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    
    print("Starting the scraper...")
    
    # Check if checkpoint exists to resume from previous run
    if os.path.exists(checkpoint_file) and start_page == 1:
        print(f"Found checkpoint file. Loading data...")
        checkpoint_df = pd.read_parquet(checkpoint_file)
        all_data = checkpoint_df.to_dict('records')
        # Get the highest page number from the checkpoint
        if all_data and len(all_data) > 0:
            # We'll start from the next page
            last_page = start_page + (len(all_data) // 12)  # Assuming 12 items per page
            current_page = last_page if last_page > 1 else 1
            print(f"Resuming from page {current_page} with {len(all_data)} records already collected")
        else:
            current_page = start_page
    else:
        all_data = []
        current_page = start_page
        print(f"Starting from page {current_page}")
    
    # Maximum retries for connection errors
    max_retries = 3
        
    # Set up garbage collection to run more frequently
    gc.enable()
    
    driver = setup_driver()
    
    try:
        print(f"Navigating to {url}")
        driver.get(url)
        
        # Wait for page to load and click search
        click_search_button(driver)
        
        # Navigate to the start page if it's different from page 1
        if start_page > 1:
            success = navigate_to_start_page(driver, start_page)
            if not success:
                print(f"Failed to navigate to start page {start_page}, starting from current page")
                current_page, _ = get_current_page_number(driver)
                if not current_page:
                    current_page = 1
                print(f"Current page: {current_page}")
        
        # Initialize a progress bar (it will update as we go)
        progress = tqdm(desc="Scraping pages", unit="page")
        
        while True:
            print(f"Scraping page {current_page}")
            # Extract data from current page with retry logic
            retry_count = 0
            page_data = []
            while retry_count < max_retries:
                try:
                    page_data = extract_table_data(driver)
                    break  # Success, exit retry loop
                except Exception as e:
                    retry_count += 1
                    print(f"Error extracting data from page {current_page}, retry {retry_count}/{max_retries}: {e}")
                    if retry_count >= max_retries:
                        print(f"Failed to extract data from page {current_page} after {max_retries} attempts")
                        break
                    time.sleep(5)  # Wait before retry
            
            # Add the data and update progress
            all_data.extend(page_data)
            progress.update(1)
            
            # Save checkpoint every 10 pages
            if current_page % 10 == 0:
                print(f"Saving checkpoint at page {current_page}...")
                checkpoint_df = pd.DataFrame(all_data)
                checkpoint_df.to_parquet(checkpoint_file, index=False)
                print(f"Checkpoint saved with {len(all_data)} records")
                
                # Force garbage collection after saving checkpoint
                gc.collect()
                
                # Clear page cache in Chrome to reduce memory usage
                driver.execute_script('window.gc();')
            
            # Check if we've reached the max pages limit
            if max_pages and current_page >= max_pages:
                print(f"Reached the specified limit of {max_pages} pages")
                break
                
            # Check if there's a next page
            if not has_next_page(driver):
                print("Reached the last page")
                break
            
            # Go to next page with retry logic
            retry_count = 0
            next_page_success = False
            while retry_count < max_retries:
                try:
                    next_page_success = click_next_page(driver)
                    if next_page_success:
                        break  # Success, exit retry loop
                    else:
                        print("Failed to navigate to next page")
                        break
                except Exception as e:
                    retry_count += 1
                    print(f"Error navigating to page {current_page + 1}, retry {retry_count}/{max_retries}: {e}")
                    if retry_count >= max_retries:
                        print(f"Failed to navigate to page {current_page + 1} after {max_retries} attempts")
                        next_page_success = False
                        break
                    time.sleep(5)  # Wait before retry
            
            if not next_page_success:
                print("Failed to navigate to next page after retries")
                break
            
            current_page += 1
            
        progress.close()
        
        # Convert to DataFrame and save as parquet
        if all_data:
            df = pd.DataFrame(all_data)
            df.to_parquet(output_file, index=False)
            print(f"Successfully scraped {len(all_data)} records and saved to {output_file}")
            
            # Clean up checkpoint file if successful
            if os.path.exists(checkpoint_file):
                os.remove(checkpoint_file)
                print("Checkpoint file removed as scraping completed successfully")
        else:
            print("No data was scraped")
            
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        driver.quit()

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Scrape the Government Gazette website')
    parser.add_argument('--max-pages', type=int, default=1721, help='Maximum number of pages to scrape')
    parser.add_argument('--start-page', type=int, default=1, help='Page to start scraping from')
    args = parser.parse_args()
    
    # Scrape with the specified parameters
    main(max_pages=args.max_pages, start_page=args.start_page)
