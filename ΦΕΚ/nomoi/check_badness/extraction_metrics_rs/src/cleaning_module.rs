use lazy_static::lazy_static;
use pyo3::prelude::*;
use pyo3::types::PyDict;
use regex::Regex;
use std::collections::{HashMap, HashSet};
use once_cell::sync::Lazy;
use serde::Serialize;

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

// Regex for the new font-based line removal
static FONT_LINE_REMOVAL_REGEX: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"MS-Bold-\d+&gt;").unwrap() // As per user example
});

/// Core text cleaning function - removes unwanted characters based on script sets
pub fn core_clean_text(text: &str, allowed_chars: &HashSet<char>, unusual_chars_set: &HashSet<char>) -> String {
    const MIN_CHARS_FOR_COMMENT: usize = 5; 
    let mut cleaned_output = String::new();

    for line in text.lines() {
        // Apply font-based line removal first
        if line.contains("MS-Bold-") && FONT_LINE_REMOVAL_REGEX.is_match(line) {
            cleaned_output.push_str(TEXT_MISSING_COMMENT);
            cleaned_output.push('\n');
            continue; // Move to the next line
        }

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
/*
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
*/

// Define the SLIMMED DOWN struct to hold only essential analysis results for CSV
#[derive(Debug, Clone, Serialize)]
pub struct SlimTextAnalysisResult {
    pub original_total_chars: usize,
    pub cleaned_total_chars: usize,
    pub original_non_whitespace_chars: Option<usize>, // Needed for percentages
    pub greek_char_count: Option<usize>,
    pub latin_char_count: Option<usize>,
    pub cleaned_text_content: String, // Added field
}

// Internal function to perform text analysis and return the SLIMMED DOWN struct
pub fn perform_text_analysis(
    text: &str, 
    allowed_chars_ref: &HashSet<char>,
    unusual_chars_ref: &HashSet<char>,
    _scripts_for_percentage_and_specific_counts: &[String], 
    calculate_specific_counts: bool 
) -> SlimTextAnalysisResult {
    
    let mut original_total_chars_val = 0;
    let mut greek_char_count_val = None;
    let mut latin_char_count_val = None;
    let mut original_non_whitespace_chars_val = None;

    if calculate_specific_counts {
        let mut nw_count = 0;
        let mut gk_count = 0; 
        let mut lat_count = 0;
        
        // Pre-fetch script sets to avoid repeated lookups in the loop
        let greek_set_opt = SCRIPT_SETS.get("greek");
        let latin_set_opt = SCRIPT_SETS.get("latin");

        for char_val in text.chars() {
            original_total_chars_val += 1;
            if !char_val.is_whitespace() {
                nw_count += 1;
                if let Some(greek_set) = greek_set_opt {
                    if greek_set.contains(&char_val) {
                        gk_count += 1;
                    }
                }
                if let Some(latin_set) = latin_set_opt {
                    if latin_set.contains(&char_val) {
                        lat_count += 1;
                    }
                }
            }
        }
        original_non_whitespace_chars_val = Some(nw_count);
        if gk_count > 0 || greek_set_opt.is_some() { // Store if explicitly looked for or if any found (even if set was None, though unlikely)
             greek_char_count_val = Some(gk_count);
        }
        if lat_count > 0 || latin_set_opt.is_some() {
            latin_char_count_val = Some(lat_count);
        }
    } else {
        original_total_chars_val = text.chars().count();
        // The following are already Option and will be None by default if not set in the calculate_specific_counts branch.
        // original_non_whitespace_chars_val = None;
        // greek_char_count_val = None;
        // latin_char_count_val = None;
    }
    
    let cleaned_text = core_clean_text(text, allowed_chars_ref, unusual_chars_ref);
    let cleaned_total_chars_val = cleaned_text.chars().count();

    SlimTextAnalysisResult {
        original_total_chars: original_total_chars_val,
        cleaned_total_chars: cleaned_total_chars_val,
        original_non_whitespace_chars: original_non_whitespace_chars_val,
        greek_char_count: greek_char_count_val,
        latin_char_count: latin_char_count_val,
        cleaned_text_content: cleaned_text, // Populate the new field
    }
}

/// Python-exposed function to analyze text metrics (still returns full HashMap for compatibility if needed elsewhere)
/// However, its internal call now uses the slimmed-down analysis.
/// If this function is ONLY used by the CSV generation, it could be removed or simplified further.
#[pyfunction]
pub fn analyze_text(py: Python, text: &str, scripts_to_keep: Vec<String>, calculate_specific_counts: bool) -> PyResult<HashMap<String, PyObject>> {
    let mut allowed_chars = HashSet::new();
    for key in &scripts_to_keep {
        if let Some(script_set) = SCRIPT_SETS.get(key) {
            allowed_chars.extend(script_set);
        }
    }
    for key_str in ["punctuation", "numbers", "common_symbols"].iter() {
        let key = key_str.to_string();
        if !scripts_to_keep.contains(&key) { 
            if let Some(script_set) = SCRIPT_SETS.get(&key) {
                allowed_chars.extend(script_set);
            }
        }
    }
    allowed_chars.insert(' ');
    allowed_chars.insert('\t');
    allowed_chars.insert('\n');
    let unusual_chars = SCRIPT_SETS.get("unusual").cloned().unwrap_or_default();

    // Call the internal slim analysis function
    let slim_result = perform_text_analysis(
        text, 
        &allowed_chars, 
        &unusual_chars, 
        &scripts_to_keep, 
        calculate_specific_counts
    );

    // Convert SlimTextAnalysisResult to HashMap for Python. This will be sparse.
    let mut py_results: HashMap<String, PyObject> = HashMap::new();
    py_results.insert("original_total_chars".to_string(), slim_result.original_total_chars.to_object(py));
    py_results.insert("cleaned_total_chars".to_string(), slim_result.cleaned_total_chars.to_object(py));
    
    let removal_ratio_score = if slim_result.original_total_chars > 0 {
        (slim_result.original_total_chars.saturating_sub(slim_result.cleaned_total_chars)) as f64 / slim_result.original_total_chars as f64
    } else {
        0.0
    };
    py_results.insert("removal_ratio_score".to_string(), removal_ratio_score.to_object(py));
    // For compatibility, also add retention_score if something expects it
    let retention_score = if slim_result.original_total_chars > 0 {
        slim_result.cleaned_total_chars as f64 / slim_result.original_total_chars as f64
    } else {
        1.0
    };
    py_results.insert("retention_score".to_string(), retention_score.to_object(py));

    if let Some(count) = slim_result.greek_char_count {
        py_results.insert("greek_char_count".to_string(), count.to_object(py));
    }
    if let Some(count) = slim_result.latin_char_count {
        py_results.insert("latin_char_count".to_string(), count.to_object(py));
    }
    if let Some(count) = slim_result.original_non_whitespace_chars {
        py_results.insert("original_non_whitespace_chars".to_string(), count.to_object(py));
    }
    
    // Comments_added is not in SlimTextAnalysisResult, so it won't be here unless calculated separately
    // py_results.insert("comments_added".to_string(), analysis_result.comments_added.to_object(py));

    // Script percentages are also not part of SlimTextAnalysisResult for now.
    // If needed by Python callers of analyze_text, this logic would need to be preserved here,
    // using slim_result.original_non_whitespace_chars.
    if calculate_specific_counts && !scripts_to_keep.is_empty() && slim_result.original_non_whitespace_chars.is_some() {
        let total_chars_for_percentage = slim_result.original_non_whitespace_chars.unwrap_or(0);
        if total_chars_for_percentage > 0 {
            let non_whitespace_chars_iter = text.chars().filter(|c| !c.is_whitespace()); // Re-iterate for accuracy with original text
            let percentages_dict = PyDict::new(py);
            for script_key_str in &scripts_to_keep { 
                if let Some(charset) = SCRIPT_SETS.get(script_key_str) { 
                    let script_count = non_whitespace_chars_iter.clone().filter(|c| charset.contains(c)).count();
                    let percentage = (script_count as f64 / total_chars_for_percentage as f64) * 100.0;
                    percentages_dict.set_item(script_key_str, percentage)?;
                }
            }
            py_results.insert("script_percentages".to_string(), percentages_dict.to_object(py));
        } else {
            py_results.insert("script_percentages".to_string(), PyDict::new(py).to_object(py));
        }
    } else {
         py_results.insert("script_percentages".to_string(), PyDict::new(py).to_object(py));
    }

    Ok(py_results)
}

/// Python-exposed function to list available script keys
#[pyfunction]
pub fn list_available_scripts() -> PyResult<Vec<String>> {
    Ok(SCRIPT_SETS.keys()
        .filter(|&k| **k != *"unusual")
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