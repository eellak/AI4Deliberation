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
    
    // Regex for HTML comments (captures the whole comment)
    pub static ref COMMENT_REGEX: Regex = Regex::new(r"<!--.*?-->").unwrap();
    
    // Regex for HTML/XML tags (for cleaning, non-comment tags)
    pub static ref ANY_TAG_CLEANING_REGEX: Regex = Regex::new(r"<[^>]*>").unwrap();

    // Central HashMap for character scripts
    pub static ref SCRIPT_SETS: HashMap<String, HashSet<char>> = {
        let mut map = HashMap::new();
        
        map.insert("latin".to_string(), "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ".chars().collect());
        
        let mut greek_chars = HashSet::new();
        for code in 0x0370..0x03E2 { if let Some(c) = std::char::from_u32(code) { greek_chars.insert(c); }}
        for code in 0x03F0..0x0400 { if let Some(c) = std::char::from_u32(code) { greek_chars.insert(c); }}
        let accented_greek = "άέήίόύώΆΈΉΊΌΎΏϊϋΪΫΐΰ";
        for c in accented_greek.chars() { greek_chars.insert(c); }
        map.insert("greek".to_string(), greek_chars);
        
        let french_specific = "àâçéèêëîïôùûüÿæœÀÂÇÉÈÊËÎÏÔÙÛÜŸÆŒ«»";
        map.insert("french".to_string(), french_specific.chars().collect());
        
        let spanish_specific = "áéíóúüñÁÉÍÓÚÜÑ¿¡";
        map.insert("spanish".to_string(), spanish_specific.chars().collect());
        
        let punctuation = ".,;:!?()[]{}\'\"&@#$%^*_-+=|\\<>/~`";
        map.insert("punctuation".to_string(), punctuation.chars().collect());
        
        let digits = "0123456789";
        map.insert("numbers".to_string(), digits.chars().collect());
        
        let common_symbols = "€£¥©®™°§";
        map.insert("common_symbols".to_string(), common_symbols.chars().collect());
        
        let mut unusual_chars = HashSet::new();
        for code in 0x0080..0x0100 { // Latin-1 Supplement
            if let Some(c) = std::char::from_u32(code) {
                if !french_specific.contains(c) && !spanish_specific.contains(c) && 
                   !accented_greek.contains(c) && !common_symbols.contains(c) && 
                   !punctuation.contains(c) {
                    unusual_chars.insert(c);
                }
            }
        }
        for code in 0x0100..0x0180 { // Latin Extended-A
            if let Some(c) = std::char::from_u32(code) {
                if !french_specific.contains(c) && !spanish_specific.contains(c) {
                    unusual_chars.insert(c);
                }
            }
        }
        for code in 0x0180..0x0250 { unusual_chars.extend(std::char::from_u32(code)); } // Latin Extended-B
        for code in 0x0250..0x02B0 { unusual_chars.extend(std::char::from_u32(code)); } // IPA Extensions
        for code in 0x1E00..0x1F00 { unusual_chars.extend(std::char::from_u32(code)); } // Latin Extended Additional
        for code in 0x03E2..0x03F0 { unusual_chars.extend(std::char::from_u32(code)); } // Coptic from Greek block
        for code in 0x2C80..0x2D00 { unusual_chars.extend(std::char::from_u32(code)); } // Dedicated Coptic block
        for code in 0x0400..0x0500 { unusual_chars.extend(std::char::from_u32(code)); } // Cyrillic block
        for code in 0x0500..0x0530 { unusual_chars.extend(std::char::from_u32(code)); } // Cyrillic Supplement
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
            // Use the COMMENT_REGEX from lazy_static which captures full HTML comments
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
        } else {
            // Optionally, log a warning if a script key is not found
            // log::warn!("Script key '{}' not found in SCRIPT_SETS", key);
        }
    }
    
    // Ensure common scripts are included even if not specified
    // Using .to_string() for comparison as keys in SCRIPT_SETS are String
    for key_str in ["punctuation", "numbers", "common_symbols"].iter() {
        let key = key_str.to_string();
        if !scripts_to_keep.contains(&key) { // Check if scripts_to_keep (Vec<String>) contains the current key (String)
            if let Some(script_set) = SCRIPT_SETS.get(&key) {
                allowed_chars.extend(script_set);
            }
        }
    }
    
    // Add essential whitespace that should always be allowed regardless of script choices
    allowed_chars.insert(' ');
    allowed_chars.insert('\t');
    allowed_chars.insert('\n'); // Though lines are processed and newlines re-added, having it in allowed_chars is safe.

    let unusual_chars = SCRIPT_SETS.get("unusual").cloned().unwrap_or_default();
    Ok(core_clean_text(text, &allowed_chars, &unusual_chars))
}

// Helper function for script percentage calculation (moved from analyze_text for clarity)
fn calc_script_percentages(py: Python, text: &str, scripts_to_keep: &[String]) -> PyResult<PyObject> {
    let percentages_dict = PyDict::new(py);
    
    if !scripts_to_keep.is_empty() {
        let non_whitespace_chars: Vec<char> = text.chars().filter(|c| !c.is_whitespace()).collect();
        let total_chars_for_percentage = non_whitespace_chars.len(); // Use count of non-whitespace for script percentage
        
        if total_chars_for_percentage > 0 {
            for script_key_str in scripts_to_keep {
                // script_key_str is already a &String, no need to convert further for SCRIPT_SETS.get()
                if let Some(charset) = SCRIPT_SETS.get(script_key_str) {
                    let script_count = non_whitespace_chars.iter()
                        .filter(|c| charset.contains(c))
                        .count();
                    
                    let percentage = (script_count as f64 / total_chars_for_percentage as f64) * 100.0;
                    percentages_dict.set_item(script_key_str, percentage)?;
                }
            }
        }
    }
    
    Ok(percentages_dict.to_object(py))
}

/// Python-exposed function to analyze text metrics
#[pyfunction]
pub fn analyze_text(py: Python, text: &str, scripts_to_keep: Vec<String>) -> PyResult<HashMap<String, PyObject>> {
    let comment_length = TEXT_MISSING_COMMENT.chars().count();

    let original_total_chars = text.chars().count();
    let original_non_whitespace = text.chars().filter(|c| !c.is_whitespace()).count();
    
    // For badness calculation: clean with a comprehensive set of "good" characters
    let mut allowed_chars_for_badness_calc = HashSet::new();
    SCRIPT_SETS.iter()
        .filter(|(k, _)| **k != "unusual") // Exclude "unusual" from what's considered "good"
        .for_each(|(_, set)| allowed_chars_for_badness_calc.extend(set));
    // Ensure basic whitespace is also considered "good" for this purpose
    allowed_chars_for_badness_calc.insert(' ');
    allowed_chars_for_badness_calc.insert('\t');
    allowed_chars_for_badness_calc.insert('\n');

    let unusual_chars_set_for_badness = SCRIPT_SETS.get("unusual").cloned().unwrap_or_default();
    let cleaned_text_for_badness = core_clean_text(text, &allowed_chars_for_badness_calc, &unusual_chars_set_for_badness);

    let cleaned_total_chars = cleaned_text_for_badness.chars().count();
    let cleaned_non_whitespace_raw = cleaned_text_for_badness.chars().filter(|c| !c.is_whitespace()).count();

    let comment_count = cleaned_text_for_badness.matches(TEXT_MISSING_COMMENT).count();
    let comment_chars_in_cleaned = comment_count * comment_length;

    let cleaned_non_whitespace_adjusted = cleaned_non_whitespace_raw.saturating_sub(comment_chars_in_cleaned);
    
    let bad_count = original_non_whitespace.saturating_sub(cleaned_non_whitespace_adjusted);
    let good_count = original_non_whitespace.saturating_sub(bad_count);
    
    let badness = if original_non_whitespace > 0 {
        bad_count as f64 / original_non_whitespace as f64
    } else {
        0.0
    };

    // For script percentages: use user-specified scripts_to_keep to create allowed_char set
    // This reuses the logic from the clean_text pyfunction for consistency
    let mut allowed_chars_for_script_calc = HashSet::new();
    for key in &scripts_to_keep {
        if let Some(script_set) = SCRIPT_SETS.get(key) {
            allowed_chars_for_script_calc.extend(script_set);
        }
    }
    for key_str in ["punctuation", "numbers", "common_symbols"].iter() {
        let key = key_str.to_string();
        if !scripts_to_keep.contains(&key) { 
            if let Some(script_set) = SCRIPT_SETS.get(&key) {
                allowed_chars_for_script_calc.extend(script_set);
        }
    }
    }
    allowed_chars_for_script_calc.insert(' ');
    allowed_chars_for_script_calc.insert('\t');
    allowed_chars_for_script_calc.insert('\n');
    
    // We need to clean the text *again* using only the characters relevant for script percentage calculation
    // This is because the content used for script percentages should only reflect the characters the user *wants* to keep.
    let unusual_chars_for_script_calc = SCRIPT_SETS.get("unusual").cloned().unwrap_or_default(); // same unusual set
    let cleaned_text_for_script_percentages = core_clean_text(text, &allowed_chars_for_script_calc, &unusual_chars_for_script_calc);
    let script_percentages = calc_script_percentages(py, &cleaned_text_for_script_percentages, &scripts_to_keep)?;

    let glyph_count_original = GLYPH_WORD_REGEX.find_iter(text).count(); // Count glyphs in original
    let unusual_chars_original_count = text.chars().filter(|c| unusual_chars_set_for_badness.contains(c)).count(); // Count unusual in original
    
    let mut result = HashMap::new();
    result.insert("badness".to_string(), badness.to_object(py));
    result.insert("bad_count".to_string(), bad_count.to_object(py));
    result.insert("good_count".to_string(), good_count.to_object(py));
    result.insert("total_chars".to_string(), original_total_chars.to_object(py));
    result.insert("total_non_whitespace".to_string(), original_non_whitespace.to_object(py));
    result.insert("cleaned_chars".to_string(), cleaned_total_chars.to_object(py)); // Based on badness cleaning
    result.insert("cleaned_non_whitespace".to_string(), cleaned_non_whitespace_raw.to_object(py)); // Based on badness cleaning
    result.insert("glyph_count".to_string(), glyph_count_original.to_object(py));
    result.insert("unusual_count".to_string(), unusual_chars_original_count.to_object(py));
    result.insert("comment_markers".to_string(), comment_count.to_object(py));
    result.insert("script_percentages".to_string(), script_percentages.to_object(py));
    
    Ok(result)
}

/// Python-exposed function to list available script keys
#[pyfunction]
pub fn list_available_scripts() -> PyResult<Vec<String>> {
    Ok(SCRIPT_SETS.keys()
        .filter(|&k| **k != *"unusual") // k is &&String, so double dereference, also dereference RHS for str vs str comparison
        .cloned()
        .collect())
}

// The batch_clean_and_analyze_files function was part of an older structure and uses different internal data types.
// It should be re-evaluated or adapted if batch analysis with these specific metrics is needed.
// For now, we focus on clean_text and analyze_text for individual strings as per the provided code.
// If you need the batch_clean_and_analyze_files functionality from your previous version,
// we would need to integrate its logic (FileOutputData, CleanAnalyzeConfig, etc.) here.

// Note: The previous FileOutputData, CleanAnalyzeConfig structs and batch_clean_and_analyze_files pyfunction
// have been removed as they are not part of the provided code snippet for this refactoring round.
// They would need to be re-added and adapted if that batch functionality is desired with the new core_clean_text.