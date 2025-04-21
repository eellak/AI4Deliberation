#!/usr/bin/env python3
"""
Improved script to fetch redirect URLs for the AI4Deliberation dataset
with proper error handling, retry logic, and diagnostic information.
"""
import pandas as pd
import aiohttp
import asyncio
import pyarrow.parquet as pq
import pyarrow as pa
from urllib.parse import quote
import logging
import time
from aiohttp import ClientTimeout, TraceConfig
import sys

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("redirect_fetcher")

# Paths
INPUT_PARQUET = 'non_law_draft_links.parquet'
OUTPUT_PARQUET = 'non_law_draft_links_with_redirects_improved.parquet'

# Configuration
MAX_RETRIES = 3
CONCURRENCY_LIMIT = 20
REQUEST_TIMEOUT = 30  # in seconds
RETRY_DELAY = 2  # in seconds


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
        session: aiohttp session
        url: Initial URL to check
        retry_count: Current retry attempt
        
    Returns:
        Final URL after redirects or None if failed
    """
    try:
        # First try a HEAD request (faster, less bandwidth)
        timeout = ClientTimeout(total=REQUEST_TIMEOUT)
        async with session.head(url, allow_redirects=True, timeout=timeout) as resp:
            status = resp.status
            if status >= 300 and status < 400:
                # It's a redirect that wasn't followed, try to get the Location header
                location = resp.headers.get('Location')
                if location:
                    logger.info(f"Found redirect in headers: {url} -> {location}")
                    return location
            elif status >= 200 and status < 300:
                # Successful HEAD request
                final_url = str(resp.url)
                if final_url != url:
                    logger.info(f"Redirect followed: {url} -> {final_url}")
                return final_url
            
        # If HEAD didn't resolve or returned an error, try GET
        async with session.get(url, allow_redirects=True, timeout=timeout) as resp:
            status = resp.status
            final_url = str(resp.url)
            
            if status >= 200 and status < 300:
                # Successful request
                if final_url != url:
                    logger.info(f"Redirect followed (GET): {url} -> {final_url}")
                return final_url
            elif status >= 300 and status < 400:
                # It's a redirect that wasn't followed
                location = resp.headers.get('Location')
                if location:
                    logger.info(f"Found redirect in headers (GET): {url} -> {location}")
                    return location
            else:
                logger.warning(f"Failed to fetch redirect for {url}: HTTP {status}")
                
            # Default: return original URL if we couldn't follow redirects
            return url
                
    except asyncio.TimeoutError:
        logger.warning(f"Timeout for {url}")
        if retry_count < MAX_RETRIES:
            logger.info(f"Retrying {url} (attempt {retry_count + 1})")
            await asyncio.sleep(RETRY_DELAY * (retry_count + 1))  # Exponential backoff
            return await fetch_redirect_url(session, url, retry_count + 1)
        return None
    except Exception as e:
        logger.error(f"Error fetching {url}: {type(e).__name__}: {e}")
        if retry_count < MAX_RETRIES:
            logger.info(f"Retrying {url} (attempt {retry_count + 1})")
            await asyncio.sleep(RETRY_DELAY * (retry_count + 1))
            return await fetch_redirect_url(session, url, retry_count + 1)
        return None


async def process_urls_batch(urls_batch, session, semaphore, start_idx):
    """Process a batch of URLs with concurrency control"""
    tasks = []
    for i, url in enumerate(urls_batch):
        # Use semaphore to limit concurrency
        tasks.append(process_url_with_semaphore(url, session, semaphore, start_idx + i))
    return await asyncio.gather(*tasks)


async def process_url_with_semaphore(url, session, semaphore, idx):
    """Process a single URL with semaphore"""
    async with semaphore:
        redirect_url = await fetch_redirect_url(session, url)
        if idx % 50 == 0:
            logger.info(f"Processed {idx} URLs")
        return redirect_url


async def process_all(df, batch_size=100):
    """Process all URLs in the dataframe with batching"""
    # Create trace config for debugging request flow
    trace_config = TraceConfig()
    trace_config.on_request_start.append(on_request_start)
    trace_config.on_request_end.append(on_request_end)
    
    # Setting up timeout and connection limits
    timeout = ClientTimeout(total=REQUEST_TIMEOUT + 5)  # Give a bit extra for connection setup
    conn = aiohttp.TCPConnector(limit=CONCURRENCY_LIMIT, force_close=True)
    
    # Semaphore for concurrency control
    semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
    
    async with aiohttp.ClientSession(connector=conn, timeout=timeout, trace_configs=[trace_config]) as session:
        urls = df['initial_url'].tolist()
        redirects = []
        
        # Process in batches for better memory management
        for i in range(0, len(urls), batch_size):
            logger.info(f"Processing batch starting at index {i}")
            batch = urls[i:i+batch_size]
            batch_results = await process_urls_batch(batch, session, semaphore, i)
            redirects.extend(batch_results)
            
            # Save intermediate results to avoid losing progress on failure
            if i > 0 and i % 500 == 0:
                temp_df = df.copy()
                temp_df.loc[:i+batch_size-1, 'redirected_url'] = redirects
                temp_df.to_parquet(f"{OUTPUT_PARQUET}.temp_{i}", index=False)
                logger.info(f"Saved intermediate results at index {i}")
        
        df['redirected_url'] = redirects
    return df


def main():
    logger.info(f"Loading parquet from {INPUT_PARQUET}")
    df = pd.read_parquet(INPUT_PARQUET)
    
    logger.info(f"Processing {len(df)} URLs to fetch redirect URLs")
    df = asyncio.run(process_all(df))
    
    # Encode URLs but preserve the redirect information
    logger.info("Encoding URLs")
    df['initial_url'] = df['initial_url'].apply(lambda x: quote(str(x), safe=':/?&=%'))
    df['redirected_url'] = df['redirected_url'].apply(
        lambda x: quote(str(x), safe=':/?&=%') if x not in (None, 'None', '') else x
    )
    
    # Fill missing redirects with original URL if it's valid
    logger.info("Filling missing redirects with original URLs where applicable")
    mask = df['redirected_url'].isnull() & df['initial_url'].notna()
    df.loc[mask, 'redirected_url'] = df.loc[mask, 'initial_url']
    
    # Save results
    logger.info(f"Saving results to {OUTPUT_PARQUET}")
    df.to_parquet(OUTPUT_PARQUET, index=False)
    
    # Print statistics
    total = len(df)
    with_redirects = df['redirected_url'].notna().sum()
    without_redirects = df['redirected_url'].isna().sum()
    logger.info(f"Total URLs: {total}")
    logger.info(f"URLs with redirects: {with_redirects} ({with_redirects/total*100:.2f}%)")
    logger.info(f"URLs without redirects: {without_redirects} ({without_redirects/total*100:.2f}%)")
    logger.info("Completed successfully")


if __name__ == "__main__":
    main()
