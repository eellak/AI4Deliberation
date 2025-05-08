use lazy_static::lazy_static;
use pyo3::prelude::*;
use pyo3::types::PyDict;
use regex::Regex;
use std::collections::{HashMap, HashSet};

// Constants
const TEXT_MISSING_COMMENT: &str = "<!-- text-missing -->";

lazy_static! {
    // Regular expressions for detection (compiled once)
    pub static ref GLYPH_TAG_REGEX_RAW: Regex = Regex::new(r"(?:^|\s)glyph<c=\d+,font=/[^>]+>(?:\s|$)").unwrap();
    pub static ref GLYPH_TAG_REGEX_HTML: Regex = Regex::new(r"(?:^|\s)glyph&lt;c=\d+,font=/[^>]+&gt;(?:\s|$)").unwrap();
    pub static ref ANY_TAG_REGEX: Regex = Regex::new(r"(?:^|\s)<[^>]*>(?:\s|$)").unwrap();
    pub static ref IS_COMMENT_REGEX: Regex = Regex::new(r"^<!--").unwrap();
    pub static ref HTML_ENTITY_REGEX: Regex = Regex::new(r"&[a-zA-Z]+;|&#\d+;|&lt;|&gt;|&amp;").unwrap();
    
    // Regex for cleaning - detect any word containing "glyph"
    pub static ref GLYPH_WORD_REGEX: Regex = Regex::new(r"\S*glyph\S*").unwrap();
    
    // Regex for HTML comments
    pub static ref COMMENT_REGEX: Regex = Regex::new(r"<!--.*?-->").unwrap();
    
    // Regex for HTML/XML tags
    pub static ref ANY_TAG_CLEANING_REGEX: Regex = Regex::new(r"<[^>]*>").unwrap();

    // Central HashMap for character scripts
    pub static ref SCRIPT_SETS: HashMap<String, HashSet<char>> = {
        let mut map = HashMap::new();
        
        // Latin basic (English)
        map.insert("latin".to_string(), "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ".chars().collect());
        
        // Greek (properly separated from Coptic)
        let mut greek_chars = HashSet::new();
        // Basic Greek characters before Coptic range (0x0370-0x03E2)
        for code in 0x0370..0x03E2 {
            if let Some(c) = std::char::from_u32(code) {
                greek_chars.insert(c);
            }
        }
        // Greek characters after Coptic range (0x03F0-0x0400)
        for code in 0x03F0..0x0400 {
            if let Some(c) = std::char::from_u32(code) {
                greek_chars.insert(c);
            }
        }
        // Add additional accented Greek (tonos, dialytika, etc.)
        let accented_greek = "άέήίόύώΆΈΉΊΌΎΏϊϋΪΫΐΰ";
        for c in accented_greek.chars() {
            greek_chars.insert(c);
        }
        map.insert("greek".to_string(), greek_chars);
        
        // French accented characters
        let french_specific = "àâçéèêëîïôùûüÿæœÀÂÇÉÈÊËÎÏÔÙÛÜŸÆŒ«»";
        map.insert("french".to_string(), french_specific.chars().collect());
        
        // Spanish accented characters
        let spanish_specific = "áéíóúüñÁÉÍÓÚÜÑ¿¡";
        map.insert("spanish".to_string(), spanish_specific.chars().collect());
        
        // Common punctuation
        let punctuation = ".,;:!?()[]{}'\"&@#$%^*_-+=|\\<>/~`";
        map.insert("punctuation".to_string(), punctuation.chars().collect());
        
        // Digits/numbers
        let digits = "0123456789";
        map.insert("numbers".to_string(), digits.chars().collect());
        
        // Common European symbols
        let common_symbols = "€£¥©®™°§";
        map.insert("common_symbols".to_string(), common_symbols.chars().collect());
        
        // Create unusual characters set - characters likely from encoding errors
        let mut unusual_chars = HashSet::new();
        
        // Latin-1 Supplement (0x0080-0x00FF) - excluding common accented chars
        for code in 0x0080..0x0100 {
            if let Some(c) = std::char::from_u32(code) {
                // Skip characters that are in any of our defined scripts
                let is_common = french_specific.contains(c) || spanish_specific.contains(c) || 
                               accented_greek.contains(c) || common_symbols.contains(c) || 
                               punctuation.contains(c);
                if !is_common {
                    unusual_chars.insert(c);
                }
            }
        }
        
        // Latin Extended-A (0x0100-0x017F) - excluding common accented chars
        for code in 0x0100..0x0180 {
            if let Some(c) = std::char::from_u32(code) {
                let is_common = french_specific.contains(c) || spanish_specific.contains(c);
                if !is_common {
                    unusual_chars.insert(c);
                }
            }
        }
        
        // Latin Extended-B (0x0180-0x024F)
        for code in 0x0180..0x0250 {
            if let Some(c) = std::char::from_u32(code) {
                unusual_chars.insert(c);
            }
        }
        
        // IPA Extensions (0x0250-0x02AF)
        for code in 0x0250..0x02B0 {
            if let Some(c) = std::char::from_u32(code) {
                unusual_chars.insert(c);
            }
        }
        
        // Latin Extended Additional (0x1E00-0x1EFF)
        for code in 0x1E00..0x1F00 {
            if let Some(c) = std::char::from_u32(code) {
                unusual_chars.insert(c);
            }
        }
        
        // Coptic from Greek and Coptic block (0x03E2-0x03F0)
        for code in 0x03E2..0x03F0 {
            if let Some(c) = std::char::from_u32(code) {
                unusual_chars.insert(c);
            }
        }
        
        // Dedicated Coptic block (0x2C80-0x2D00)
        for code in 0x2C80..0x2D00 {
            if let Some(c) = std::char::from_u32(code) {
                unusual_chars.insert(c);
            }
        }
        
        // Cyrillic block (0x0400-0x0500)
        for code in 0x0400..0x0500 {
            if let Some(c) = std::char::from_u32(code) {
                unusual_chars.insert(c);
            }
        }
        
        // Cyrillic Supplement (0x0500-0x0530)
        for code in 0x0500..0x0530 {
            if let Some(c) = std::char::from_u32(code) {
                unusual_chars.insert(c);
            }
        }
        
        map.insert("unusual".to_string(), unusual_chars);
        
        map
    };
}

/// Core text cleaning function - removes unwanted characters based on script sets
pub fn core_clean_text(text: &str, allowed_chars: &HashSet<char>, unusual_chars_set: &HashSet<char>) -> String {
    const MIN_CHARS_FOR_COMMENT: usize = 5;
    let mut cleaned_output = String::new();

    for line in text.lines() {
        let mut processed_line_segment = String::new();
        let mut current_line_removed_chars_buffer = String::new();

        // 1. Tag Handling
        let mut line_after_tag_handling = String::new();
        let mut last_pos = 0;
        for mat in ANY_TAG_CLEANING_REGEX.find_iter(line) {
            line_after_tag_handling.push_str(&line[last_pos..mat.start()]);
            let tag_content = mat.as_str();
            if COMMENT_REGEX.is_match(tag_content) {
                line_after_tag_handling.push_str(tag_content);
            } else {
                for char_in_tag in tag_content.chars().filter(|c| !c.is_whitespace()) {
                    current_line_removed_chars_buffer.push(char_in_tag);
                }
            }
            last_pos = mat.end();
        }
        line_after_tag_handling.push_str(&line[last_pos..]);

        // 2. Glyph Word Removal
        let mut line_after_glyph_removal = String::new();
        last_pos = 0;
        for mat in GLYPH_WORD_REGEX.find_iter(&line_after_tag_handling) {
            line_after_glyph_removal.push_str(&line_after_tag_handling[last_pos..mat.start()]);
            for char_in_glyph in mat.as_str().chars().filter(|c| !c.is_whitespace()) {
                current_line_removed_chars_buffer.push(char_in_glyph);
            }
            last_pos = mat.end();
        }
        line_after_glyph_removal.push_str(&line_after_tag_handling[last_pos..]);

        // 3. Unusual Character Removal
        for ch in line_after_glyph_removal.chars() {
            if unusual_chars_set.contains(&ch) && !allowed_chars.contains(&ch) {
                if !ch.is_whitespace() {
                    current_line_removed_chars_buffer.push(ch);
                }
            } else {
                processed_line_segment.push(ch);
            }
        }
        
        let removed_chars_on_line_for_comment_decision = current_line_removed_chars_buffer.chars().count();

        // 4. Comment Insertion Logic
        if !processed_line_segment.trim().is_empty() {
            if removed_chars_on_line_for_comment_decision >= MIN_CHARS_FOR_COMMENT {
                cleaned_output.push_str(processed_line_segment.trim_end());
                cleaned_output.push(' ');
                cleaned_output.push_str(TEXT_MISSING_COMMENT);
            } else {
                cleaned_output.push_str(&processed_line_segment);
            }
        } else {
            if removed_chars_on_line_for_comment_decision >= MIN_CHARS_FOR_COMMENT 
               && line.chars().any(|c| !c.is_whitespace()) {
                cleaned_output.push_str(TEXT_MISSING_COMMENT);
            } else {
                cleaned_output.push_str(&processed_line_segment);
            }
        }
        cleaned_output.push('\n');
    }

    if !text.is_empty() && text.ends_with('\n') {
        cleaned_output
    } else {
        cleaned_output.trim_end_matches('\n').to_string()
    }
}

/// Python-exposed function to clean a single string
#[pyfunction]
pub fn clean_text(text: &str, scripts_to_keep: Vec<String>) -> PyResult<String> {
    let mut allowed_chars = HashSet::new();
    for key in &scripts_to_keep {
        if let Some(script_set) = SCRIPT_SETS.get(key) {
            allowed_chars.extend(script_set);
        }
    }
    
    // Ensure common scripts are included even if not specified
    for key in ["punctuation", "numbers", "common_symbols"] {
        if !scripts_to_keep.contains(&key.to_string()) {
            if let Some(script_set) = SCRIPT_SETS.get(key) {
                allowed_chars.extend(script_set);
            }
        }
    }
    
    let unusual_chars = SCRIPT_SETS.get("unusual").cloned().unwrap_or_default();
    Ok(core_clean_text(text, &allowed_chars, &unusual_chars))
}

/// Python-exposed function to analyze text metrics
#[pyfunction]
pub fn analyze_text(py: Python, text: &str, scripts_to_keep: Vec<String>) -> PyResult<HashMap<String, PyObject>> {
    // Constants for our analysis
    let comment_length = TEXT_MISSING_COMMENT.chars().count();
    
    // --- Get character counts from original text ---
    let original_total_chars = text.chars().count();
    let original_non_whitespace = text.chars().filter(|c| !c.is_whitespace()).count();
    
    // --- First, clean the text (which is much faster) ---
    let mut allowed_chars_for_cleaning = HashSet::new();
    // Use all known scripts for badness calculation to isolate truly problematic content
    SCRIPT_SETS.iter()
        .filter(|(k, _)| **k != "unusual")
        .for_each(|(_, set)| allowed_chars_for_cleaning.extend(set));
    
    let unusual_chars_set = SCRIPT_SETS.get("unusual").cloned().unwrap_or_default();
    let cleaned_text = core_clean_text(text, &allowed_chars_for_cleaning, &unusual_chars_set);
    
    // --- Get character counts from cleaned text ---
    let cleaned_total_chars = cleaned_text.chars().count();
    let cleaned_non_whitespace = cleaned_text.chars().filter(|c| !c.is_whitespace()).count();
    
    // --- Count the comment markers to adjust our calculations ---
    let comment_count = cleaned_text.matches(TEXT_MISSING_COMMENT).count();
    let comment_chars_added = comment_count * comment_length;
    
    // --- Calculate bad characters ---
    // Adjust for added comment markers
    let cleaned_adjusted = cleaned_non_whitespace.saturating_sub(comment_chars_added);
    let bad_count = if original_non_whitespace > cleaned_adjusted {
        original_non_whitespace - cleaned_adjusted
    } else {
        // Failsafe: if cleaned text is somehow longer than original
        0
    };
    
    let good_count = original_non_whitespace.saturating_sub(bad_count);
    
    // --- Calculate badness score ---
    let badness = if original_non_whitespace > 0 {
        bad_count as f64 / original_non_whitespace as f64
    } else {
        0.0
    };
    
    // --- Calculate script percentages on cleaned text ---
    // For script percentages, use requested scripts to keep
    let mut allowed_chars_for_script_calc = HashSet::new();
    for key in &scripts_to_keep {
        if let Some(script_set) = SCRIPT_SETS.get(key) {
            allowed_chars_for_script_calc.extend(script_set);
        }
    }
    
    // Also include common scripts for script percentage calculation
    for key in ["punctuation", "numbers", "common_symbols"] {
        if !scripts_to_keep.contains(&key.to_string()) {
            if let Some(script_set) = SCRIPT_SETS.get(key) {
                allowed_chars_for_script_calc.extend(script_set);
            }
        }
    }
    
    let cleaned_text_for_script_calc = core_clean_text(text, &allowed_chars_for_script_calc, &unusual_chars_set);
    let script_percentages = calc_script_percentages(py, &cleaned_text_for_script_calc, &scripts_to_keep)?;

    // Count glyphs and unusual chars in original text
    let glyph_count = GLYPH_WORD_REGEX.find_iter(text).count();
    let unusual_count = text.chars().filter(|c| unusual_chars_set.contains(c)).count();
    
    // Build result dictionary
    let mut result = HashMap::new();
    result.insert("badness".to_string(), badness.to_object(py));
    result.insert("bad_count".to_string(), bad_count.to_object(py));
    result.insert("good_count".to_string(), good_count.to_object(py));
    result.insert("total_chars".to_string(), original_total_chars.to_object(py));
    result.insert("total_non_whitespace".to_string(), original_non_whitespace.to_object(py));
    result.insert("cleaned_chars".to_string(), cleaned_total_chars.to_object(py));
    result.insert("cleaned_non_whitespace".to_string(), cleaned_non_whitespace.to_object(py));
    result.insert("glyph_count".to_string(), glyph_count.to_object(py));
    result.insert("unusual_count".to_string(), unusual_count.to_object(py));
    result.insert("comment_markers".to_string(), comment_count.to_object(py));
    result.insert("script_percentages".to_string(), script_percentages.to_object(py));
    
    Ok(result)
}

// Helper function for script percentage calculation
fn calc_script_percentages(py: Python, text: &str, scripts_to_keep: &[String]) -> PyResult<PyObject> {
    let percentages_dict = PyDict::new(py);
    
    if !scripts_to_keep.is_empty() {
        let non_whitespace_chars: Vec<char> = text.chars().filter(|c| !c.is_whitespace()).collect();
        let total_chars = non_whitespace_chars.len();
        
        if total_chars > 0 {
            for script_key in scripts_to_keep {
                if let Some(charset) = SCRIPT_SETS.get(script_key) {
                    let script_count = non_whitespace_chars.iter()
                        .filter(|c| charset.contains(c))
                        .count();
                    
                    let percentage = (script_count as f64 / total_chars as f64) * 100.0;
                    percentages_dict.set_item(script_key, percentage)?;
                }
            }
        }
    }
    
    Ok(percentages_dict.to_object(py))
}

/// Python-exposed function to list available script keys
#[pyfunction]
pub fn list_available_scripts() -> PyResult<Vec<String>> {
    Ok(SCRIPT_SETS.keys()
        .filter(|&k| k != "unusual")
        .cloned()
        .collect())
}
