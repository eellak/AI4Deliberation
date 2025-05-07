use lazy_static::lazy_static;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyDict;
use regex::Regex;
use std::collections::{HashMap, HashSet};
use std::path::Path;
use std::fs;

// Regular expressions for detection (compiled once)
lazy_static! {
    // Modified to only count tags at word boundaries or line start/end
    static ref GLYPH_TAG_REGEX_RAW: Regex = Regex::new(r"(?:^|\s)glyph<c=\d+,font=/[^>]+>(?:\s|$)").unwrap();
    static ref GLYPH_TAG_REGEX_HTML: Regex = Regex::new(r"(?:^|\s)glyph&lt;c=\d+,font=/[^>]+&gt;(?:\s|$)").unwrap();
    static ref ANY_TAG_REGEX: Regex = Regex::new(r"(?:^|\s)<[^>]*>(?:\s|$)").unwrap();
    static ref IS_COMMENT_REGEX: Regex = Regex::new(r"^<!--").unwrap();
    static ref HTML_ENTITY_REGEX: Regex = Regex::new(r"&[a-zA-Z]+;|&#\d+;|&lt;|&gt;|&amp;").unwrap();
    
    // Regex for cleaning - detect any word containing "glyph"
    static ref GLYPH_WORD_REGEX: Regex = Regex::new(r"\S*glyph\S*").unwrap();
    
    // Regex for HTML comments
    static ref COMMENT_REGEX: Regex = Regex::new(r"<!--.*?-->").unwrap();
    
    // Regex for HTML/XML tags
    static ref ANY_TAG_CLEANING_REGEX: Regex = Regex::new(r"<[^>]*>").unwrap();

    // Central HashMap for character scripts
    static ref SCRIPT_SETS: HashMap<String, HashSet<char>> = {
        let mut map = HashMap::new();
        
        // Latin basic (English)
        map.insert("lat".to_string(), "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ".chars().collect());
        
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
        map.insert("gre".to_string(), greek_chars);
        
        // French accented characters
        let french_specific = "àâçéèêëîïôùûüÿæœÀÂÇÉÈÊËÎÏÔÙÛÜŸÆŒ«»";
        map.insert("fra".to_string(), french_specific.chars().collect());
        
        // Spanish accented characters
        let spanish_specific = "áéíóúüñÁÉÍÓÚÜÑ¿¡";
        map.insert("spa".to_string(), spanish_specific.chars().collect());
        
        // Common punctuation
        let punctuation = ".,;:!?()[]{}'\"&@#$%^*_-+=|\\<>/~`";
        map.insert("punct".to_string(), punctuation.chars().collect());
        
        // Digits
        let digits = "0123456789";
        map.insert("num".to_string(), digits.chars().collect());
        
        // Common European symbols
        let common_symbols = "€£¥©®™°§";
        map.insert("sym".to_string(), common_symbols.chars().collect());
        
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

#[pyfunction]
fn analyze_text(text: &str, scripts_to_keep: Vec<String>) -> PyResult<HashMap<String, PyObject>> {
    Python::with_gil(|py| {
        // Constants for our analysis
        const TEXT_MISSING_COMMENT: &str = "<!-- text-missing -->";
        let comment_length = TEXT_MISSING_COMMENT.chars().count();
        
        // --- Get character counts from original text ---
        let original_total_chars = text.chars().count();
        let original_non_whitespace = text.chars().filter(|c| !c.is_whitespace()).count();
        
        // --- First, clean the text (which is much faster) ---
        let cleaned_text = clean_text(text, scripts_to_keep.clone())?;
        
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
        let mut script_percentages = HashMap::new();
        
        // Only do script analysis if we have scripts to analyze
        if !scripts_to_keep.is_empty() {
            // Setup our character sets
            let mut script_counts: HashMap<String, usize> = HashMap::new();
            for script in &scripts_to_keep {
                script_counts.insert(script.clone(), 0);
            }
            
            // Count characters by script (on cleaned text only)
            for c in cleaned_text.chars() {
                if c.is_whitespace() {
                    continue;
                }
                
                // Check which scripts this character belongs to
                for script in &scripts_to_keep {
                    if let Some(charset) = SCRIPT_SETS.get(script) {
                        if charset.contains(&c) {
                            *script_counts.entry(script.clone()).or_insert(0) += 1;
                        }
                    }
                }
            }
            
            // Calculate percentages
            let divisor = if cleaned_non_whitespace > 0 { cleaned_non_whitespace } else { 1 } as f64;
            for (script, &count) in &script_counts {
                let percentage = (count as f64 / divisor) * 100.0;
                script_percentages.insert(script.clone(), percentage);
            }
        }
        
        // --- Get glyph and unusual character counts ---
        // We can get these directly by regex on the original text
        let glyph_count = GLYPH_WORD_REGEX.find_iter(text).count();
        
        let unusual_count = if let Some(unusual_chars) = SCRIPT_SETS.get("unusual") {
            text.chars().filter(|c| unusual_chars.contains(c)).count()
        } else {
            0
        };
        
        // --- Prepare Python Result Dictionary ---
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
        
        let percentages_dict = PyDict::new(py);
        for (script, percentage) in script_percentages {
            percentages_dict.set_item(script, percentage)?;
        }
        result.insert("script_percentages".to_string(), percentages_dict.to_object(py));
        
        Ok(result)
    })
}

#[pyfunction]
fn clean_text(text: &str, scripts_to_keep: Vec<String>) -> PyResult<String> {
    // Combine all the requested scripts into a single set of allowed characters
    let mut allowed_chars = HashSet::new();
    
    for script in &scripts_to_keep {
        if let Some(charset) = SCRIPT_SETS.get(script) {
            for &c in charset {
                allowed_chars.insert(c);
            }
        } else {
            return Err(PyValueError::new_err(format!("Unknown script code: {}", script)));
        }
    }
    
    // Get the unusual characters set
    let unusual_chars = match SCRIPT_SETS.get("unusual") {
        Some(set) => set,
        None => return Err(PyValueError::new_err("Unable to find unusual character set definition")),
    };
    
    // Start cleaning process
    let mut result = String::new();
    
    // Process the file line by line for better comment handling
    for line in text.lines() {
        // Check if this line is a comment already
        let is_comment_line = COMMENT_REGEX.is_match(line);
        
        if is_comment_line {
            result.push_str(line);
            result.push('\n');
            continue;
        }
        
        // Step 1: Replace glyph words
        let glyph_matches: Vec<_> = GLYPH_WORD_REGEX.find_iter(line).collect();
        
        let mut line_after_glyph_cleanup = line.to_string();
        let mut total_glyph_chars_removed = 0;
        
        // Replace glyph words in reverse order to maintain indices
        for mat in glyph_matches.iter().rev() {
            let removed_text = &line[mat.start()..mat.end()];
            total_glyph_chars_removed += removed_text.len();
            line_after_glyph_cleanup.replace_range(mat.start()..mat.end(), "");
        }
        
        // Step 2: Remove unusual characters
        let mut final_line = String::new();
        let mut total_unusual_chars_removed = 0;
        
        // Check each character
        for c in line_after_glyph_cleanup.chars() {
            if unusual_chars.contains(&c) && !allowed_chars.contains(&c) {
                total_unusual_chars_removed += 1;
            } else {
                final_line.push(c);
            }
        }
        
        // Step 3: Remove HTML/XML tags but preserve comments
        let _unused = String::new(); // Variable removed - was causing a warning
        
        // First store all comments in the line
        let mut comments = Vec::new();
        let mut comment_positions = Vec::new();
        
        for comment_match in COMMENT_REGEX.find_iter(&final_line) {
            comments.push(comment_match.as_str().to_string());
            comment_positions.push((comment_match.start(), comment_match.end()));
        }
        
        // Define the clean line variable
        let line_after_tag_cleanup;
        
        if !comments.is_empty() {
            // Line has comments - remove all other tags but preserve comments
            let mut temp_line = final_line.clone();
            
            // Replace all non-comment tags
            for tag_match in ANY_TAG_CLEANING_REGEX.find_iter(&final_line) {
                // Check if this tag is part of a comment
                let is_comment = comment_positions.iter()
                    .any(|(start, end)| tag_match.start() >= *start && tag_match.end() <= *end);
                
                if !is_comment {
                    // Replace with empty string if not a comment
                    temp_line = temp_line.replace(tag_match.as_str(), "");
                }
            }
            line_after_tag_cleanup = temp_line;
        } else {
            // No comments, remove all tags
            line_after_tag_cleanup = ANY_TAG_CLEANING_REGEX.replace_all(&final_line, "").to_string();
        }
        
        // Step 4: Add "text-missing" comment if needed
        let total_chars_removed = total_glyph_chars_removed + total_unusual_chars_removed;
        let clean_line = line_after_tag_cleanup.trim();
        
        if total_chars_removed >= 5 && !clean_line.is_empty() && !COMMENT_REGEX.is_match(clean_line) {
            // Add missing text comment
            result.push_str(clean_line);
            result.push_str(" <!-- text-missing -->");
            result.push('\n');
        } else if total_chars_removed >= 5 && clean_line.is_empty() {
            // Line is empty after cleaning, add standalone comment
            result.push_str("<!-- text-missing -->");
            result.push('\n');
        } else {
            // No significant removal or already has a comment
            if !clean_line.is_empty() {
                result.push_str(clean_line);
                result.push('\n');
            } else {
                // Empty line after cleaning but not from significant removal
                result.push('\n');
            }
        }
    }
    
    Ok(result)
}

#[pyfunction]
fn process_file(
    input_path: &str, 
    output_path: Option<&str>,
    scripts_to_keep: Vec<String>
) -> PyResult<HashMap<String, PyObject>> {
    // Read file content
    let content = match fs::read_to_string(input_path) {
        Ok(content) => content,
        Err(e) => return Err(PyValueError::new_err(format!("Failed to read file: {}", e))),
    };
    
    // Analyze the text
    let analysis = analyze_text(&content, scripts_to_keep.clone())?;
    
    // Clean the text if output path is provided
    if let Some(output) = output_path {
        // Clean the text
        let cleaned_text = clean_text(&content, scripts_to_keep)?;
        
        // Ensure parent directory exists
        if let Some(parent) = Path::new(output).parent() {
            if !parent.exists() {
                if let Err(e) = fs::create_dir_all(parent) {
                    return Err(PyValueError::new_err(format!("Failed to create output directory: {}", e)));
                }
            }
        }
        
        // Write the cleaned file
        if let Err(e) = fs::write(output, cleaned_text) {
            return Err(PyValueError::new_err(format!("Failed to write cleaned file: {}", e)));
        }
    }
    
    Ok(analysis)
}

#[pyfunction]
fn list_available_scripts() -> PyResult<Vec<String>> {
    Ok(SCRIPT_SETS.keys()
        .filter(|&k| k != "unusual") // Don't expose the unusual set as keepable
        .cloned()
        .collect())
}

#[pymodule]
fn text_cleaner_rs(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(analyze_text, m)?)?;
    m.add_function(wrap_pyfunction!(clean_text, m)?)?;
    m.add_function(wrap_pyfunction!(process_file, m)?)?;
    m.add_function(wrap_pyfunction!(list_available_scripts, m)?)?;
    Ok(())
}
