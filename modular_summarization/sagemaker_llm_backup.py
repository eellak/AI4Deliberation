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

# Schema mapping for TGI's native JSON schema enforcement
try:
    from .schemas import (
        LAW_MOD_SCHEMA,
        LAW_NEW_SCHEMA,
        CHAPTER_SUMMARY_SCHEMA,
        PART_SUMMARY_SCHEMA,
        POLISHED_SUMMARY_SCHEMA,
        CITIZEN_POLISH_SUMMARY_SCHEMA,
        NARRATIVE_PLAN_SCHEMA,
        NARRATIVE_SECTION_SCHEMA,
        DRAFT_PARAGRAPHS_SCHEMA,
        STYLISTIC_CRITIQUE_SCHEMA,
    )
    
    schema_map = {
        "LAW_MOD": LAW_MOD_SCHEMA,
        "LAW_NEW": LAW_NEW_SCHEMA,
        "CHAPTER_SUM": CHAPTER_SUMMARY_SCHEMA,
        "PART_SUM": PART_SUMMARY_SCHEMA,
        "POLISHED_SUMMARY": POLISHED_SUMMARY_SCHEMA,
        "CITIZEN_POLISH_SUMMARY": CITIZEN_POLISH_SUMMARY_SCHEMA,
        "NARRATIVE_PLAN": NARRATIVE_PLAN_SCHEMA,
        "NARRATIVE_SECTION": NARRATIVE_SECTION_SCHEMA,
        "DRAFT_PARAGRAPHS": DRAFT_PARAGRAPHS_SCHEMA,
        "STYLISTIC_CRITIQUE": STYLISTIC_CRITIQUE_SCHEMA,
    }
    SCHEMAS_AVAILABLE = True
    # Compile Lark grammars once for all tags so we can ship them to TGI
    grammar_map = {tag: JsonSchemaParser(sch).json_schema_to_lark() for tag, sch in schema_map.items()}
except ImportError:
    logger.warning("Schemas not available for SageMaker integration")
    schema_map = {}
    SCHEMAS_AVAILABLE = False
    grammar_map = {}

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


# Stub generator for dry run mode (matching llm.py)
def _stub_generator(prompt: str, max_tokens: int) -> str:
    """Return deterministic minimal JSON for testing."""
    if "[SCHEMA:LAW_MOD]" in prompt:
        return json.dumps({
            "law_reference": "ν. 0/0000",
            "article_number": "άρθρο Χ",
            "change_type": "τροποποιείται",
            "major_change_summary": "stub",
            "key_themes": ["stub"],
        }, ensure_ascii=False)
    elif "[SCHEMA:NARRATIVE_PLAN]" in prompt:
        return json.dumps({
            "overall_narrative_arc": "stub arc",
            "protagonist": "stub protagonist",
            "problem": "stub problem",
            "narrative_sections": [{
                "section_title": "Ενότητα 1",
                "section_role": "stub role",
                "source_chapters": [0, 1],
            }],
        }, ensure_ascii=False)
    elif "[SCHEMA:NARRATIVE_SECTION]" in prompt:
        return json.dumps({"current_section_text": "stub section"}, ensure_ascii=False)
    else:
        return json.dumps({"summary": "stub"}, ensure_ascii=False)


def _build_sagemaker_generator() -> Callable[[str, int], str]:
    """Build the real SageMaker generator with schema enforcement."""
    endpoint_name = os.getenv("SAGEMAKER_ENDPOINT_NAME", "").strip()
    
    if not endpoint_name:
        logger.warning("SAGEMAKER_ENDPOINT_NAME not set, falling back to stub")
        return _stub_generator
    
    client = _get_sagemaker_client()
    if client is None:
        logger.warning("SageMaker client unavailable, falling back to stub")
        return _stub_generator
    
    def sagemaker_generate(prompt: str, max_tokens: int) -> str:
        """Generate text using SageMaker endpoint."""
        try:
            # Check for schema tag
            schema_match = re.match(r'\[SCHEMA:(\w+)\]', prompt)
            
            # If schema tag present, enhance the prompt with clearer JSON instructions
            if schema_match:
                schema_name = schema_match.group(1)
                # Remove the schema tag from prompt
                clean_prompt = prompt.replace(f'[SCHEMA:{schema_name}]', '').strip()
                
                # Add explicit JSON generation instruction
                enhanced_prompt = f"""{clean_prompt}

IMPORTANT: You MUST respond with ONLY valid JSON. No explanations, no markdown, just the JSON object.
Start your response with {{ and end with }}.
"""
                prompt_to_send = enhanced_prompt
            else:
                prompt_to_send = prompt
            
            # Prepare the payload
            payload = {
                "inputs": prompt_to_send,
                "parameters": {
                    "max_new_tokens": max_tokens,
                    "do_sample": False,  # Deterministic generation
                    "temperature": 0.01,  # Very low but > 0 as required by TGI
                    "return_full_text": False,
                }
            }
            
            # Attach grammar parameter if we have one for this schema tag
            if schema_match and SCHEMAS_AVAILABLE:
                schema_name = schema_match.group(1)
                grammar_str = grammar_map.get(schema_name)
                if grammar_str:
                    payload["parameters"]["grammar"] = grammar_str
                    logger.debug(f"Grammar attached for schema: {schema_name}")

            logger.debug(f"Invoking SageMaker endpoint: {endpoint_name}")
            
            response = client.invoke_endpoint(
                EndpointName=endpoint_name,
                ContentType='application/json',
                Body=json.dumps(payload)
            )
            
            result = json.loads(response['Body'].read().decode())
            
            # Extract generated text
            if isinstance(result, list) and len(result) > 0:
                generated_text = result[0].get('generated_text', '')
            elif isinstance(result, dict):
                generated_text = result.get('generated_text', '')
            else:
                logger.error(f"Unexpected response format: {type(result)}")
                generated_text = str(result)
            
            logger.debug(f"Generated {len(generated_text)} characters")
            return generated_text
            
        except Exception as e:
            logger.error(f"SageMaker generation failed: {e}")
            # Return minimal valid JSON on error
            if schema_match:
                return _stub_generator(prompt, max_tokens)
            return ""
    
    logger.info(f"SageMaker generator configured for endpoint: {endpoint_name}")
    return sagemaker_generate


def get_generator(*, dry_run: bool = False) -> Callable[[str, int], str]:
    """Return an LLM generation function (matching llm.py interface).
    
    Parameters
    ----------
    dry_run : bool, default False
        If True, returns a lightweight stub generator (no API calls).
    """
    if dry_run:
        return _stub_generator
    return _build_sagemaker_generator()


# Compatibility function for existing code
get_sagemaker_generator = get_generator


if __name__ == "__main__":
    # Test when run directly
    logging.basicConfig(level=logging.INFO)
    
    generator = get_generator(dry_run=False)
    test_prompt = '[SCHEMA:CHAPTER_SUM] Test chapter summary generation'
    response = generator(test_prompt, 100)
    
    try:
        parsed = json.loads(response)
        print("✓ Valid JSON generated:", json.dumps(parsed, ensure_ascii=False, indent=2))
    except json.JSONDecodeError:
        print("✗ Invalid JSON:", response)