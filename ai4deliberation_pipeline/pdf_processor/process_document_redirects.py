#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Process document redirects for the AI4Deliberation PDF processing pipeline.

This script reads the document URLs from a parquet file, resolves redirects
for each URL, and saves the updated parquet file with redirected URLs.
"""

import os
import pandas as pd
import aiohttp
import asyncio
import logging
import time
from aiohttp import ClientTimeout, TraceConfig
from pathlib import Path
import sys

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/mnt/data/AI4Deliberation/pdf_pipeline/redirect_log.txt')
    ]
)
logger = logging.getLogger(__name__)

# Constants
WORKSPACE_DIR = '/mnt/data/AI4Deliberation/pdf_pipeline/workspace'
PARQUET_FILE = os.path.join(WORKSPACE_DIR, 'documents.parquet')
ERROR_FILE = os.path.join(WORKSPACE_DIR, 'redirect_errors.parquet')

# Create workspace directory if it doesn't exist
os.makedirs(WORKSPACE_DIR, exist_ok=True)

# Configuration
MAX_RETRIES = 3
CONCURRENCY_LIMIT = 20
REQUEST_TIMEOUT = 30  # in seconds
RETRY_DELAY = 2  # in seconds

# Trace config callbacks for monitoring requests
async def on_request_start(session, trace_config_ctx, params):
    """Trace config callback for request start"""
    trace_config_ctx.start = time.time()
    logger.debug(f"Starting request to {params.url}")

async def on_request_end(session, trace_config_ctx, params):
    """Trace config callback for request end"""
    elapsed = time.time() - trace_config_ctx.start
    logger.debug(f"Request to {params.url} took {elapsed:.2f}s with status {params.response.status}")

async def fetch_redirect_url(session, url, retry_count=0):
    """
    Fetch the final URL after following redirects.
    
    Args:
        session: aiohttp ClientSession
        url: The initial URL to follow
        retry_count: Current retry attempt
        
    Returns:
        The final URL after following all redirects, or the original URL on failure
    """
    if retry_count > MAX_RETRIES:
        logger.error(f"Max retries exceeded for {url}")
        return url, "max_retries_exceeded"
    
    try:
        # Follow redirects to get the final URL
        async with session.get(
            url, 
            allow_redirects=True, 
            timeout=ClientTimeout(total=REQUEST_TIMEOUT),
            ssl=False  # Disable SSL verification for potentially invalid certificates
        ) as response:
            
            # Get the final URL
            final_url = str(response.url)
            logger.debug(f"Redirected {url} -> {final_url}")
            
            # Check if the response is OK (2xx)
            if response.status // 100 == 2:
                return final_url, None
            else:
                logger.warning(f"Non-200 status for {url}: {response.status}")
                return final_url, f"status_{response.status}"
                
    except asyncio.TimeoutError:
        logger.warning(f"Timeout for {url}, retrying ({retry_count+1}/{MAX_RETRIES})")
        await asyncio.sleep(RETRY_DELAY)
        return await fetch_redirect_url(session, url, retry_count + 1)
        
    except aiohttp.ClientError as e:
        logger.warning(f"Client error for {url}: {e}, retrying ({retry_count+1}/{MAX_RETRIES})")
        await asyncio.sleep(RETRY_DELAY)
        return await fetch_redirect_url(session, url, retry_count + 1)
        
    except Exception as e:
        logger.error(f"Unexpected error for {url}: {e}")
        return url, str(e)

async def process_url_with_semaphore(url, session, semaphore, idx):
    """Process a single URL with semaphore to limit concurrency"""
    async with semaphore:
        logger.debug(f"Processing URL {idx}: {url}")
        redirected_url, error = await fetch_redirect_url(session, url)
        return url, redirected_url, error

async def process_urls_batch(urls_batch, session, semaphore, start_idx):
    """Process a batch of URLs with concurrency control"""
    tasks = []
    for i, url in enumerate(urls_batch):
        task = asyncio.ensure_future(
            process_url_with_semaphore(url, session, semaphore, start_idx + i)
        )
        tasks.append(task)
    return await asyncio.gather(*tasks)

async def process_all(df, batch_size=100):
    """Process all URLs in the dataframe with batching"""
    # Create trace config for request monitoring
    trace_config = TraceConfig()
    trace_config.on_request_start.append(on_request_start)
    trace_config.on_request_end.append(on_request_end)
    
    # Initialize results
    url_results = []
    
    # Create semaphore to limit concurrency
    semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
    
    # Create client session
    async with aiohttp.ClientSession(trace_configs=[trace_config]) as session:
        # Process in batches
        total_urls = len(df)
        urls = df['initial_url'].tolist()
        
        for batch_start in range(0, total_urls, batch_size):
            batch_end = min(batch_start + batch_size, total_urls)
            logger.info(f"Processing batch {batch_start//batch_size + 1}: URLs {batch_start}-{batch_end-1}")
            
            # Process batch
            batch_results = await process_urls_batch(
                urls[batch_start:batch_end], 
                session, 
                semaphore,
                batch_start
            )
            url_results.extend(batch_results)
            
            logger.info(f"Completed batch {batch_start//batch_size + 1} ({batch_end}/{total_urls})")
    
    # Create result dataframe
    results_df = pd.DataFrame(url_results, columns=['initial_url', 'redirected_url', 'error'])
    
    # Merge with original dataframe
    merged_df = df.merge(results_df, on='initial_url', how='left')
    
    # Count successes and failures
    success_count = merged_df[merged_df['error'].isna()].shape[0]
    error_count = merged_df[~merged_df['error'].isna()].shape[0]
    
    logger.info(f"URL processing complete: {success_count} successful, {error_count} errors")
    
    return merged_df

def main():
    logger.info("Starting document redirect processing")
    
    # Check if input parquet exists
    if not os.path.exists(PARQUET_FILE):
        logger.error(f"Input parquet file not found: {PARQUET_FILE}")
        logger.info("Please run export_documents_to_parquet.py first")
        return
    
    try:
        # Read input parquet
        df = pd.read_parquet(PARQUET_FILE)
        logger.info(f"Loaded {len(df)} documents from {PARQUET_FILE}")
        
        # Process URLs
        loop = asyncio.get_event_loop()
        result_df = loop.run_until_complete(process_all(df))
        
        # Remove error column from final output
        if 'error' in result_df.columns:
            error_count = result_df['error'].notna().sum()
            if error_count > 0:
                logger.warning(f"Found {error_count} URLs with errors")
                # Save error dataframe for inspection
                error_df = result_df[result_df['error'].notna()]
                error_df.to_parquet(ERROR_FILE, index=False)
                logger.info(f"Saved {len(error_df)} error records to {ERROR_FILE}")
            
            # For URLs with errors, use the original URL
            result_df.loc[result_df['error'].notna(), 'redirected_url'] = result_df.loc[result_df['error'].notna(), 'initial_url']
            result_df = result_df.drop('error', axis=1)
        
        # Save results back to the same parquet file, overwriting the original
        result_df.to_parquet(PARQUET_FILE, index=False)
        logger.info(f"Updated {len(result_df)} documents with redirected URLs in {PARQUET_FILE}")
        
        logger.info("URL redirect processing complete")
        logger.info(f"Next step: Run the PDF processing script on {PARQUET_FILE}")
        
    except Exception as e:
        logger.error(f"Error processing document redirects: {e}")

if __name__ == "__main__":
    main()
