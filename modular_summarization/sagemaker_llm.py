"""SageMaker LLM integration for the modular summarizer.

This module provides a drop-in replacement for the local LLM generator
that uses AWS SageMaker endpoints instead.
"""
import os
import json
import logging
import re
from typing import Callable, Optional
from functools import lru_cache
from lmformatenforcer import JsonSchemaParser

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# JSON schema → Lark grammar mapping for server-side enforcement via TGI
# ---------------------------------------------------------------------------
try:
    from modular_summarization import schemas as _schemas  # local project schemas

    _TAG_TO_SCHEMA = {
        "LAW_MOD":                _schemas.LAW_MOD_SCHEMA,
        "LAW_NEW":                _schemas.LAW_NEW_SCHEMA,
        "CHAPTER_SUM":            _schemas.CHAPTER_SUMMARY_SCHEMA,
        "SINGLE_CHAPTER_SUMMARY": _schemas.CHAPTER_SUMMARY_SCHEMA,
        "PART_SUM":               _schemas.PART_SUMMARY_SCHEMA,
        "NARRATIVE_PLAN":         _schemas.NARRATIVE_PLAN_SCHEMA,
        "NARRATIVE_SECTION":      _schemas.NARRATIVE_SECTION_SCHEMA,
        "CITIZEN_POLISH_SUMMARY": _schemas.CITIZEN_POLISH_SUMMARY_SCHEMA,
        "STYLISTIC_CRITIQUE":     _schemas.STYLISTIC_CRITIQUE_SCHEMA,
        "POLISHED_SUMMARY":       _schemas.POLISHED_SUMMARY_SCHEMA,
    }

    _TAG_TO_GRAMMAR = {tag: JsonSchemaParser(schema).json_schema_to_lark()
                       for tag, schema in _TAG_TO_SCHEMA.items()}
except Exception as _e:  # pragma: no cover
    logger.warning("Schema import failed – grammar enforcement disabled: %s", _e)
    _TAG_TO_SCHEMA = {}
    _TAG_TO_GRAMMAR = {}

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    logger.info("python-dotenv not installed, using system environment variables only")

try:
    import boto3
    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False
    logger.warning("boto3 not available - SageMaker integration disabled")


@lru_cache(maxsize=1)
def _get_sagemaker_client():
    """Get or create a cached SageMaker runtime client."""
    if not BOTO3_AVAILABLE:
        return None
    
    try:
        region = os.getenv("AWS_REGION", "eu-central-1")
        client = boto3.client('runtime.sagemaker', region_name=region)
        logger.info(f"SageMaker runtime client initialized for region: {region}")
        return client
    except Exception as e:
        logger.error(f"Failed to initialize SageMaker client: {e}")
        return None


def build_structured_prompt(prompt: str, schema_name: str) -> str:
    """Build a structured prompt that guides JSON generation."""
    
    templates = {
        "CHAPTER_SUM": '{\n  "summary": "Your comprehensive chapter summary in Greek..."\n}',
        "PART_SUM": '{\n  "summary": "Your comprehensive part summary in Greek..."\n}',
        "CITIZEN_POLISH_SUMMARY": '{\n  "summary_text": "Your citizen-friendly summary in Greek..."\n}',
        "LAW_MOD": '{\n  "law_reference": "ν. ΧΧΧΧ/ΧΧΧΧ",\n  "article_number": "άρθρο Χ",\n  "change_type": "τροποποιείται",\n  "major_change_summary": "description",\n  "key_themes": ["theme1", "theme2"]\n}'
    }
    
    template = templates.get(schema_name, templates["CHAPTER_SUM"])
    base_prompt = prompt.replace(f'[SCHEMA:{schema_name}]', '').strip()
    
    return f"""{base_prompt}

CRITICAL: You MUST respond with ONLY a JSON object in this exact format:
{template}

Rules:
1. Start your response with {{ and end with }}
2. Use double quotes for all strings
3. Ensure valid JSON syntax
4. No text before or after the JSON object
5. If content is too long, truncate with "..."

JSON Response:"""


def extract_json_from_response(text: str) -> str:
    """Extract and clean JSON from model response."""
    # Remove markdown code blocks
    text = re.sub(r'```(?:json)?\s*', '', text)
    text = re.sub(r'```\s*$', '', text)
    
    # Find JSON object
    start = text.find('{')
    if start == -1:
        return text
    
    # Find matching closing brace
    brace_count = 0
    end = -1
    for i in range(start, len(text)):
        if text[i] == '{':
            brace_count += 1
        elif text[i] == '}':
            brace_count -= 1
            if brace_count == 0:
                end = i
                break
    
    if end == -1:
        # Truncated JSON - try to fix
        json_str = text[start:]
        # Add missing quotes
        if json_str.count('"') % 2 == 1:
            json_str += '"'
        # Close arrays and objects
        json_str += ']' * (json_str.count('[') - json_str.count(']'))
        json_str += '}' * (json_str.count('{') - json_str.count('}'))
    else:
        json_str = text[start:end+1]
    
    # Clean up common issues
    json_str = re.sub(r',\s*}', '}', json_str)
    json_str = re.sub(r',\s*]', ']', json_str)
    
    try:
        # Validate JSON
        parsed = json.loads(json_str)
        return json.dumps(parsed, ensure_ascii=False)
    except:
        return json_str


def get_sagemaker_generator() -> Optional[Callable[[str, int], str]]:
    """Return a SageMaker-based generator function or None if unavailable.
    
    Returns
    -------
    Optional[Callable[[str, int], str]]
        A function that takes (prompt, max_tokens) and returns generated text,
        or None if SageMaker is not configured/available.
    """
    endpoint_name = os.getenv("SAGEMAKER_ENDPOINT_NAME", "").strip()
    
    if not endpoint_name:
        logger.warning("SAGEMAKER_ENDPOINT_NAME not set in environment")
        return None
    
    client = _get_sagemaker_client()
    if client is None:
        return None
    
    def sagemaker_generate(prompt: str, max_tokens: int) -> str:
        """Generate text using SageMaker endpoint.
        
        Parameters
        ----------
        prompt : str
            The input prompt
        max_tokens : int
            Maximum number of tokens to generate
            
        Returns
        -------
        str
            Generated text
        """
        try:
            # Check for schema tag and enhance prompt
            enhanced_prompt = prompt
            schema_match = re.match(r'\[SCHEMA:(\w+)\]', prompt)
            expecting_json = bool(schema_match) or '{' in prompt
            grammar_str = None
            schema_dict = None
            
            if schema_match:
                schema_name = schema_match.group(1)
                enhanced_prompt = build_structured_prompt(prompt, schema_name)
                logger.debug(f"Using structured prompt for schema: {schema_name}")
                grammar_str = _TAG_TO_GRAMMAR.get(schema_name)
                schema_dict = _TAG_TO_SCHEMA.get(schema_name)
            
            # Prepare the payload for HuggingFace TGI format
            payload = {
                "inputs": enhanced_prompt,
                "parameters": {
                    "max_new_tokens": max_tokens,
                    "temperature": 0.1,  # Low for more deterministic output
                    "do_sample": True,
                    "top_p": 0.9,  # Focus on high probability tokens
                    "repetition_penalty": 1.1,
                    "return_full_text": False,  # Only return generated text
                    "stop_sequences": ["\n\n", "```", "</json>"]  # Stop generation at these sequences
                }
            }
            
            if grammar_str:
                payload["parameters"]["grammar"] = grammar_str
            elif schema_dict is not None:
                payload["parameters"]["json_schema"] = schema_dict
            logger.debug(f"Invoking SageMaker endpoint: {endpoint_name}")
            
            response = client.invoke_endpoint(
                EndpointName=endpoint_name,
                ContentType='application/json',
                Body=json.dumps(payload)
            )
            
            result = json.loads(response['Body'].read().decode())
            
            # Handle different response formats
            if isinstance(result, list) and len(result) > 0:
                # Response is a list of generations
                generated_text = result[0].get('generated_text', '')
            elif isinstance(result, dict):
                # Response is a single generation
                generated_text = result.get('generated_text', '')
            else:
                logger.error(f"Unexpected response format: {type(result)}")
                generated_text = str(result)
            
            logger.debug(f"Generated {len(generated_text)} characters")
            
            # If expecting JSON, extract and clean it
            if expecting_json:
                cleaned_json = extract_json_from_response(generated_text)
                logger.debug(f"Extracted JSON: {cleaned_json[:100]}...")
                return cleaned_json
            
            return generated_text
            
        except Exception as e:
            logger.error(f"SageMaker generation failed: {e}")
            # Return empty string on error to match stub behavior
            return ""
    
    logger.info(f"SageMaker generator configured for endpoint: {endpoint_name}")
    return sagemaker_generate


def test_sagemaker_connection():
    """Test the SageMaker connection with a simple prompt.
    
    Returns
    -------
    bool
        True if connection successful, False otherwise
    """
    generator = get_sagemaker_generator()
    if generator is None:
        logger.error("Failed to get SageMaker generator")
        return False
    
    try:
        test_prompt = "Hello, this is a test. Please respond with 'Test successful'."
        response = generator(test_prompt, 20)
        logger.info(f"SageMaker test response: {response}")
        return bool(response)
    except Exception as e:
        logger.error(f"SageMaker connection test failed: {e}")
        return False


if __name__ == "__main__":
    # Simple test when run directly
    logging.basicConfig(level=logging.INFO)
    if test_sagemaker_connection():
        print("✓ SageMaker connection successful")
    else:
        print("✗ SageMaker connection failed")