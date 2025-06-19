"""Stage 3 Expansion: Two-stage narrative summarization workflow.

This module implements the expanded Stage 3 workflow which replaces the previous
one-shot part-level summarization with a two-stage process:

1. Narrative Planning: Creates a structured narrative plan with story beats
2. Chunk Synthesis: Generates a paragraph for each story beat

This produces a more cohesive, narrative-driven summary of the legislative part.
"""
import json
import logging
from typing import Callable, Dict, List, Optional, Any, TypeVar, Union, cast

from .law_types import NarrativePlan, GeneratedParagraph, StoryBeat
from .stage23_helpers_v2 import (
    construct_stage3_plan_input,
    construct_stage3_synth_input,
)
from .prompts import get_prompt
from .compression import summarization_budget

_log = logging.getLogger(__name__)

# Type aliases for clarity
LLMGeneratorFn = Callable[[str, int], str]
JSON = Dict[str, Any]
T = TypeVar('T')


def _try_fix_incomplete_json(json_text: str) -> Optional[str]:
    """Attempt to fix incomplete JSON by balancing braces and adding missing quotes.
    
    Parameters
    ----------
    json_text : str
        Potentially incomplete JSON text
        
    Returns
    -------
    Optional[str]
        Fixed JSON string if successful, None otherwise
    """
    # Strategy 1: Fix truncated strings and add missing closing tokens
    try:
        fixed = json_text.strip()
        
        # If the text ends with an incomplete string (no closing quote), close it
        if fixed.endswith('"'):
            # Already ends with quote - that's good
            pass
        elif '"' in fixed and not fixed.endswith('"'):
            # Check if we're in the middle of a string value
            # Find the last opening quote that doesn't have a closing quote
            last_quote_pos = fixed.rfind('"')
            if last_quote_pos >= 0:
                # Check if this quote is escaped
                escape_count = 0
                for i in range(last_quote_pos - 1, -1, -1):
                    if fixed[i] == '\\':
                        escape_count += 1
                    else:
                        break
                
                # If odd number of escapes, the quote is escaped, so we need to close the string
                if escape_count % 2 == 1 or not (last_quote_pos == 0 or fixed[last_quote_pos-1] in ',:[]{}'):
                    fixed += '"'
        
        # Count and balance braces/brackets
        open_braces = fixed.count('{')
        close_braces = fixed.count('}')
        open_brackets = fixed.count('[')
        close_brackets = fixed.count(']')
        
        # Add missing closing brackets first
        if open_brackets > close_brackets:
            fixed += ']' * (open_brackets - close_brackets)
            
        # Add missing closing braces  
        if open_braces > close_braces:
            fixed += '}' * (open_braces - close_braces)
        
        # Try to parse the fixed JSON
        json.loads(fixed)
        return fixed
        
    except (json.JSONDecodeError, Exception):
        pass
    
    # Strategy 2: Find the last complete array element and truncate there
    try:
        # Look for the last complete object in the narrative_sections array
        narrative_start = json_text.find('"narrative_sections": [')
        if narrative_start >= 0:
            # Find the last complete object (ends with })
            sections_start = json_text.find('[', narrative_start) + 1
            
            # Find complete objects by tracking braces
            brace_count = 0
            last_complete_obj_end = -1
            in_string = False
            escape_next = False
            
            for i in range(sections_start, len(json_text)):
                char = json_text[i]
                
                if escape_next:
                    escape_next = False
                    continue
                    
                if char == '\\':
                    escape_next = True
                    continue
                    
                if char == '"' and not escape_next:
                    in_string = not in_string
                    continue
                    
                if not in_string:
                    if char == '{':
                        brace_count += 1
                    elif char == '}':
                        brace_count -= 1
                        if brace_count == 0:
                            # Found end of complete object
                            last_complete_obj_end = i
            
            if last_complete_obj_end > 0:
                # Truncate after the last complete object and close the array/object
                truncated = json_text[:last_complete_obj_end + 1] + ']}'
                try:
                    json.loads(truncated)
                    return truncated
                except json.JSONDecodeError:
                    pass
                    
    except Exception:
        pass
    
    # Strategy 3: Remove the incomplete last element and close properly
    try:
        # Find the last comma in the narrative_sections array
        narrative_start = json_text.find('"narrative_sections": [')
        if narrative_start >= 0:
            # Find the last complete comma-separated item
            last_comma = json_text.rfind(',', narrative_start)
            if last_comma > narrative_start:
                # Truncate before the incomplete item
                truncated = json_text[:last_comma] + ']}'
                try:
                    json.loads(truncated)
                    return truncated
                except json.JSONDecodeError:
                    pass
                    
    except Exception:
        pass
    
    return None


def plan_narrative(
    chapter_summaries: Union[List[str], Dict[str, str]],
    intro_lines: Optional[List[str]],
    generator_fn: LLMGeneratorFn,
    max_tokens: Optional[int] = None,
) -> NarrativePlan:
    """Generate a narrative plan using either prompt A (with Σκοπός/Αντικείμενο) or B.
    
    Parameters
    ----------
    chapter_summaries : List[str]
        The chapter summaries from Stage 2
    intro_lines : List[str], optional
        Optional list where intro_lines[0] is Σκοπός and intro_lines[1] is Αντικείμενο
    generator_fn : Callable
        Function that takes (prompt_text, max_tokens) and returns LLM response
    max_tokens : int, optional
        Maximum tokens for the LLM call; if None, will calculate based on input size
        
    Returns
    -------
    NarrativePlan
        The structured narrative plan
    
    Raises
    ------
    ValueError
        If the LLM response cannot be parsed as valid JSON with the expected schema
    """
    # Use dynamic prompt with beat placeholders
    prompt_key = "stage3_plan_dyn"

    # Prepare keyed mapping regardless of list/dict input
    input_data = construct_stage3_plan_input(chapter_summaries, intro_lines)
    input_json_str = json.dumps(input_data, ensure_ascii=False, indent=2)

    # Beat-range heuristics ---------------------------------------------------
    n_chapters = len(chapter_summaries) if isinstance(chapter_summaries, (list, dict)) else 1
    min_beats = max(2, n_chapters // 3) if n_chapters > 1 else 1
    max_beats = n_chapters

    # Token budget ------------------------------------------------------------
    if max_tokens is None:
        total_input_text = " ".join(list(chapter_summaries.values()) if isinstance(chapter_summaries, dict) else chapter_summaries)
        if intro_lines:
            total_input_text += " ".join(intro_lines)
        word_count = len(total_input_text.split())
        target_words = max(int(word_count * 0.7), 300)
        max_tokens = int(target_words * 4)

    # Build prompt ------------------------------------------------------------
    try:
        from .prompts import get_prompt
        template_raw = get_prompt(prompt_key)
        # Compose dynamic placeholder values
        allowed_keys_descriptive = list(input_data["περιλήψεις_κεφαλαίων"].keys())
        allowed_keys_csv = ", ".join(allowed_keys_descriptive)
        allowed_range = f"0–{n_chapters - 1}"
        prompt_filled = template_raw.format(
            min_beats=min_beats,
            max_beats=max_beats,
            allowed_keys_csv=allowed_keys_csv,
            allowed_range=allowed_range,
            input_data_json=input_json_str,
        )
        prompt = prompt_filled
    except KeyError as e:
        _log.error(f"Prompt key '{prompt_key}' not found")
        raise
    except Exception as e:
        _log.error(f"Failed to format prompt: {e}")
        raise
    
    # -----------------------------------------------------------------------
    # Call the LLM with validation + retry -----------------------------------
    # -----------------------------------------------------------------------
    from .validator import generate_with_validation, validate_narrative_plan

    # Allow both descriptive keys (e.g. "kefalaio_0") **and** bare numeric indices
    allowed_keys: List[Union[str, int]] = list(input_data["περιλήψεις_κεφαλαίων"].keys())
    # Add numeric indices (int and str) up to the number of chapters so the validator
    # accepts LLM outputs that reference 0-based integers instead of the descriptive keys.
    allowed_keys.extend(range(n_chapters))
    allowed_keys.extend([str(i) for i in range(n_chapters)])

    def _plan_validator(raw: str, keys):
        try:
            json_str = extract_json_from_text(raw)
            plan_obj = json.loads(json_str)
        except Exception as exc:
            return [f"JSON extraction/parsing error: {exc}"]
        return validate_narrative_plan(plan_obj, keys)

    _log.info(f"Generating narrative plan with validation (max_tokens={max_tokens})")

    try:
        response, retries = generate_with_validation(
            prompt,
            max_tokens,
            generator_fn,
            _plan_validator,
            validator_args=(allowed_keys,),
            max_retries=2,
        )
        _log.debug(f"Narrative plan generated after {retries} retries")
    except Exception as e:
        _log.error(f"Failed to generate validated narrative plan: {e}")
        raise

    # Parse validated response ------------------------------------------------
    try:
        json_str = extract_json_from_text(response)
        narrative_plan = json.loads(json_str)
    except Exception as e:
        _log.error(f"Unexpected parse failure after validation: {e}")
        raise ValueError("Could not parse narrative plan JSON after validation") from e
    
    # Parse the response (expected to be JSON format)
    try:
        # Log the raw response for debugging
        _log.debug(f"Raw LLM response (first 100 chars): {response[:100]}...")
        
        # Extract JSON if wrapped in markdown or other text
        try:
            json_str = extract_json_from_text(response)
            _log.debug(f"Extracted JSON string (first 100 chars): {json_str[:100]}...")
        except ValueError as e:
            _log.error(f"Failed to extract JSON from LLM response: {e}")
            _log.debug(f"Raw response: {response}")
            raise ValueError(f"Could not extract JSON from LLM output") from e
        
        # Parse the JSON string
        try:
            narrative_plan = json.loads(json_str)
        except json.JSONDecodeError as e:
            _log.error(f"JSON parsing error: {e}")
            _log.debug(f"Problematic JSON string: {json_str}")
            
            # Try additional fixes for common issues
            if '\\"' in json_str or '\\n' in json_str:
                # Handle escaped quotes and newlines
                _log.debug("Attempting to fix escaped characters in JSON")
                fixed_json = json_str.replace('\\"', '"').replace('\\n', '\n')
                narrative_plan = json.loads(fixed_json)
                _log.debug("Fixed escaped characters in JSON successfully")
            else:
                raise
        
        # Validate the schema (basic check for required keys)
        required_keys = [
            "overall_narrative_arc", 
            "protagonist", 
            "problem", 
            "narrative_sections"
        ]
        
        missing_keys = [key for key in required_keys if key not in narrative_plan]
        if missing_keys:
            _log.error(f"Missing required keys in narrative plan: {missing_keys}")
            _log.debug(f"Available keys: {list(narrative_plan.keys())}")
            raise ValueError(f"Invalid narrative plan format: missing keys {missing_keys}")
        
        # Validate the structure of narrative_sections
        if not isinstance(narrative_plan["narrative_sections"], list):
            raise ValueError("narrative_sections must be a list")
        
        for i, section in enumerate(narrative_plan["narrative_sections"]):
            section_required_keys = ["section_title", "section_role", "source_chapters"]
            section_missing_keys = [key for key in section_required_keys if key not in section]
            if section_missing_keys:
                _log.error(f"Missing required keys in narrative section {i}: {section_missing_keys}")
                raise ValueError(f"Invalid narrative section {i}: missing keys {section_missing_keys}")
            
            if not isinstance(section["source_chapters"], list):
                raise ValueError(f"source_chapters must be a list in section {i}")
        
        # Validate that we have at least one story beat
        story_beats = narrative_plan.get("narrative_sections", [])
        if not story_beats or not isinstance(story_beats, list):
            _log.error("No story beats found in narrative plan or invalid format")
            _log.debug(f"Story beats: {story_beats}")
            raise ValueError("Narrative plan must contain at least one story beat")
            
        _log.info(f"Successfully parsed narrative plan with {len(story_beats)} story beats")
            
        # Cast to specific type for better type checking
        return cast(NarrativePlan, narrative_plan)
        
    except (json.JSONDecodeError, ValueError) as e:
        _log.error(f"Failed to parse narrative plan: {e}")
        _log.error(f"Raw response: {response}")
        raise ValueError(f"Invalid narrative plan format: {e}") from e


def synthesize_paragraph(
    narrative_plan: NarrativePlan,
    chapter_summaries: Union[List[str], Dict[str, str]],
    beat_index: int,
    generator_fn: LLMGeneratorFn,
    max_tokens: Optional[int] = None,
) -> str:
    """Generate a single paragraph for one story beat.
    
    Parameters
    ----------
    narrative_plan : NarrativePlan
        The complete narrative plan
    chapter_summaries : List[str]
        All chapter summaries, either list or dict keyed by chapter IDs
    beat_index : int
        Index of the story beat to synthesize
    generator_fn : Callable
        Function that takes (prompt_text, max_tokens) and returns LLM response
    max_tokens : int, optional
        Maximum tokens for this paragraph; if None, will calculate based on source chapters
        
    Returns
    -------
    str
        The generated paragraph text
    """
    # -------------------------------------------------------------------
    # Prepare input data for synthesis
    # -------------------------------------------------------------------
    input_data = construct_stage3_synth_input(narrative_plan, chapter_summaries, beat_index)
    input_json_str = json.dumps(input_data, ensure_ascii=False, indent=2)
    
    # Calculate token budget if not specified
    if max_tokens is None:
        source_keys = narrative_plan["narrative_sections"][beat_index].get("source_chapters", [])
        total_source_text = ""
        if isinstance(chapter_summaries, dict):
            for k in source_keys:
                txt = chapter_summaries.get(k)
                if txt:
                    total_source_text += txt + " "
        else:
            for k in source_keys:
                # Convert potential keyed string to index
                if isinstance(k, int):
                    idx = k
                else:
                    try:
                        idx = int(str(k).split("_")[-1])
                    except ValueError:
                        continue
                if 0 <= idx < len(chapter_summaries):
                    total_source_text += chapter_summaries[idx] + " "
        # Target around 30% compression for each paragraph
        word_count = len(total_source_text.split())
        target_words = max(int(word_count * 0.3), 60)
        max_tokens = int(target_words * 3)
    
    # Get the prompt template and append input data
    prompt_template = get_prompt("stage3_synth")
    prompt = prompt_template + "\n\n**Δεδομένα Εισόδου:**\n" + input_json_str
    
    # Call the LLM
    _log.info(f"Synthesizing paragraph for beat {beat_index} (max_tokens={max_tokens})")
    response = generator_fn(prompt, max_tokens)
    
    # Parse the response (expected to be JSON with "paragraph" key)
    try:
        json_str = extract_json_from_text(response)
        result = json.loads(json_str)
        
        if not isinstance(result, dict) or "paragraph" not in result:
            raise ValueError("Response missing 'paragraph' key")
        
        paragraph: str = result["paragraph"]
        return paragraph
    except (json.JSONDecodeError, ValueError) as e:
        _log.warning(f"Failed to parse JSON paragraph, using raw text: {e}")
        # Fallback: return the raw text if JSON parsing fails
        # Strip any markdown code block markers
        cleaned = response.strip()
        if cleaned.startswith('```'):
            parts = cleaned.split('```')
            if len(parts) >= 3:
                cleaned = parts[1]
                if cleaned.startswith('json'):
                    cleaned = cleaned[4:].strip()
        return cleaned


def summarize_single_chapter(
    chapter_text: str,
    generator_fn: LLMGeneratorFn,
    max_tokens: int = 600,
) -> str:
    """Fast-track summarization for Parts with a single Chapter."""
    prompt = get_prompt("stage3_single_chapter") + "\n\n**Κείμενο Κεφαλαίου:**\n" + chapter_text
    resp = generator_fn(prompt, max_tokens)
    try:
        json_str = extract_json_from_text(resp)
        obj = json.loads(json_str)
        if isinstance(obj, dict) and "summary" in obj:
            return obj["summary"]
    except Exception:
        pass
    return resp.strip()


# ---------------------------------------------------------------------------
# Public orchestration helper
# ---------------------------------------------------------------------------

def generate_part_summary(
    chapter_summaries: Union[List[str], Dict[str, str]],
    intro_lines: Optional[List[str]] = None,
    generator_fn: LLMGeneratorFn = None,
    max_tokens_total: Optional[int] = None,
) -> str:
    """Generate a complete part summary using the two-stage workflow.
    
    This function orchestrates the complete Stage 3 process:
    1. Generate a narrative plan
    2. For each story beat, generate a paragraph
    3. Combine paragraphs into a cohesive summary
    
    Parameters
    ----------
    chapter_summaries : List[str]
        The chapter summaries from Stage 2
    intro_lines : List[str], optional
        Optional intro texts (Σκοπός, Αντικείμενο)
    generator_fn : Callable
        Function to call the LLM
    max_tokens_total : int, optional
        Overall token budget; if None, calculated based on input size
        
    Returns
    -------
    str
        The complete part summary, with paragraphs joined by newlines
    """
    if not generator_fn:
        raise ValueError("LLM generator function is required")
    
    # Calculate total token budget if not specified
    if max_tokens_total is None:
        total_input_text = " ".join(list(chapter_summaries.values()) if isinstance(chapter_summaries, dict) else chapter_summaries)
        if intro_lines:
            total_input_text += " ".join(intro_lines)
        
        # Use the overall budget helper with 0.6 compression ratio
        # Note: summarization_budget expects text input, not word count
        budget_info = summarization_budget(total_input_text, compression_ratio=0.6)
        max_tokens_total = budget_info['token_limit']
        _log.debug(f"Calculated total budget: {max_tokens_total} tokens from {len(total_input_text)} chars input")
    
    # Budget allocation: 30% for planning, 70% for synthesis, with minimums
    planning_budget = max(int(max_tokens_total * 0.3), 800)  # Minimum 800 tokens for planning
    synthesis_budget_total = max_tokens_total - planning_budget
    
    # If planning minimum exceeds total, increase total budget
    if planning_budget > max_tokens_total * 0.5:
        max_tokens_total = planning_budget * 2  # Ensure reasonable split
        synthesis_budget_total = max_tokens_total - planning_budget
        _log.warning(f"Increased total budget to {max_tokens_total} to accommodate minimum planning budget")
    
    # Step 1: Generate the narrative plan
    # Fast-track if only one chapter
    n_chaps = len(chapter_summaries) if isinstance(chapter_summaries, (list, dict)) else 1
    if n_chaps == 1:
        single_text = next(iter(chapter_summaries.values())) if isinstance(chapter_summaries, dict) else chapter_summaries[0]
        return summarize_single_chapter(single_text, generator_fn)

    narrative_plan = plan_narrative(
        chapter_summaries,
        intro_lines,
        generator_fn,
        max_tokens=planning_budget
    )
    
    # Step 2: Generate paragraphs for each story beat
    num_beats = len(narrative_plan["narrative_sections"])
    paragraphs = []
    
    # Allocate synthesis budget evenly across beats, with minimum 600 tokens per beat
    per_beat_budget = max(synthesis_budget_total // num_beats if num_beats > 0 else 0, 600)
    
    # If the per-beat budget exceeds what we have, adjust total budget
    if per_beat_budget * num_beats > synthesis_budget_total:
        _log.warning(f"Increasing synthesis budget to ensure {per_beat_budget} tokens per beat")
        synthesis_budget_total = per_beat_budget * num_beats
    
    for beat_idx in range(num_beats):
        paragraph = synthesize_paragraph(
            narrative_plan,
            chapter_summaries,
            beat_idx,
            generator_fn,
            max_tokens=per_beat_budget
        )
        paragraphs.append(paragraph)
    
    # Step 3: Join paragraphs with newlines
    # Always start with "Ο σκοπός του μέρους είναι" as required
    if not paragraphs:
        return "Ο σκοπός του μέρους είναι να ρυθμίσει τα ζητήματα που σχετίζονται με την εφαρμογή του."
    
    first_para = paragraphs[0]
    if not first_para.startswith("Ο σκοπός του μέρους είναι"):
        paragraphs[0] = f"Ο σκοπός του μέρους είναι {first_para[0].lower() + first_para[1:]}"
    
    return "\n\n".join(paragraphs)


def extract_json_from_text(text: str) -> str:
    """Extract JSON object from potentially non-JSON text.
    
    This function handles common patterns in LLM responses where JSON may be
    wrapped in markdown code blocks or preceded/followed by explanatory text.
    
    Parameters
    ----------
    text : str
        Input text that might contain JSON
        
    Returns
    -------
    str
        Extracted JSON string
        
    Raises
    ------
    ValueError
        If no JSON-like content could be found
    """
    _log.debug(f"Attempting to extract JSON from text of length {len(text)}")
    text = text.strip()
    
    # Case 1: Already valid JSON
    try:
        json.loads(text)
        _log.debug("Text was already valid JSON")
        return text
    except json.JSONDecodeError as e:
        _log.debug(f"Text is not valid JSON as-is: {e}")
        pass
    
    # Case 2: JSON in markdown code block
    if '```' in text:
        _log.debug("Detected markdown code blocks, attempting to extract JSON")
        code_blocks = text.split('```')
        for i in range(1, len(code_blocks), 2):
            # Skip language identifier if present
            block = code_blocks[i].strip()
            if block.startswith('json'):
                block = block[4:].strip()
            elif block.startswith('JSON'):
                block = block[4:].strip()
            
            # Try parsing this block
            try:
                json.loads(block)
                _log.debug("Successfully extracted JSON from code block")
                return block
            except json.JSONDecodeError as e:
                _log.debug(f"Code block {i//2+1} is not valid JSON: {e}, attempting to fix")
                # Try to fix incomplete JSON by balancing braces
                fixed_block = _try_fix_incomplete_json(block)
                if fixed_block:
                    _log.debug("Successfully fixed incomplete JSON in code block")
                    return fixed_block
                continue
    
    # Case 3: Find content between { and }
    start_idx = text.find('{')
    end_idx = text.rfind('}')
    if start_idx >= 0 and end_idx > start_idx:
        _log.debug(f"Found potential JSON object from char {start_idx} to {end_idx}")
        json_candidate = text[start_idx:end_idx+1]
        try:
            json.loads(json_candidate)
            _log.debug("Successfully extracted JSON from text using braces")
            return json_candidate
        except json.JSONDecodeError as e:
            _log.debug(f"Extracted content is not valid JSON: {e}")
    
    # Case 4: Try applying some cleanup first
    _log.debug("Applying advanced text cleanup and retrying JSON extraction")
    # Remove any leading/trailing whitespace and quotes
    cleaned_text = text.strip().strip('"\'')
    
    # Handle text that might start with a backtick but not properly formatted as code block
    if cleaned_text.startswith('`') and not cleaned_text.startswith('```'):
        cleaned_text = cleaned_text.strip('`')
    
    # Try again with the cleaned text
    try:
        json.loads(cleaned_text)
        _log.debug("Successfully parsed JSON after text cleanup")
        return cleaned_text
    except json.JSONDecodeError:
        pass
    
    # Case 5: Fix common LLM formatting issues - unexpected linebreaks or missing braces
    _log.debug("Attempting to fix potential JSON formatting issues")
    if text.find('{') >= 0:
        # Sometimes LLM adds line breaks or spaces before the opening brace
        text_from_brace = text[text.find('{'):]
        try:
            json.loads(text_from_brace)
            _log.debug("Successfully parsed JSON after trimming text before opening brace")
            return text_from_brace
        except json.JSONDecodeError:
            pass
    
    # Case 6: Last resort - try to recover malformed JSON by balancing braces
    _log.debug("Attempting to fix incomplete JSON as last resort")
    try:
        start = text.find('{')
        if start >= 0:
            text_from_start = text[start:]
            fixed_json = _try_fix_incomplete_json(text_from_start)
            if fixed_json:
                _log.debug("Successfully fixed incomplete JSON")
                return fixed_json
    except Exception as e:
        _log.debug(f"JSON fixing failed: {e}")
    
    # Log the problematic text for debugging
    preview = text[:100] + '...' if len(text) > 100 else text
    _log.error(f"Failed to extract valid JSON. Text preview: {preview}")
    
    # Could not extract valid JSON
    raise ValueError("No valid JSON found in text")
