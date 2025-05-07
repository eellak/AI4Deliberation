use lazy_static::lazy_static;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyDict;
use regex::Regex;
use std::collections::{HashMap, HashSet};
use std::fs::{self};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use walkdir::WalkDir;
use rayon::prelude::*;
use rayon::ThreadPoolBuilder;

lazy_static! {
    // Regular expressions for detection (compiled once)
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

fn _internal_core_clean_text_logic(text: &str, allowed_chars: &HashSet<char>) -> String {
    const TEXT_MISSING_COMMENT: &str = "<!-- text-missing -->";
    const MIN_CHARS_FOR_COMMENT: usize = 5; // Minimum non-tag, non-whitespace chars removed to trigger comment

    let unusual_chars_set = SCRIPT_SETS.get("unusual").cloned().unwrap_or_default();
    let mut cleaned_output = String::new();
    // Accumulates removed chars for the current line to decide on comment insertion.
    // Resets for each line *after* comment decision for that line has been made.
    // let mut removed_chars_on_line_for_comment_decision: usize = 0;

    for line in text.lines() {
        let mut processed_line_segment = String::new(); // Builds the potentially cleaned version of the current line
        let mut current_line_removed_chars_buffer = String::new(); // Chars removed from this line (tags, glyphs, unusual)

        // 1. Handle tags: Preserve comments, remove others, count removed chars from non-comment tags.
        let mut line_after_tag_handling = String::new();
        let mut last_pos = 0;
        for mat in ANY_TAG_CLEANING_REGEX.find_iter(line) {
            line_after_tag_handling.push_str(&line[last_pos..mat.start()]);
            let tag_content = mat.as_str();
            if COMMENT_REGEX.is_match(tag_content) {
                line_after_tag_handling.push_str(tag_content); // Preserve comment
            } else {
                // Tag is removed; add its non-whitespace chars to buffer for comment decision
                for char_in_tag in tag_content.chars() {
                    if !char_in_tag.is_whitespace() {
                        current_line_removed_chars_buffer.push(char_in_tag);
                    }
                }
            }
            last_pos = mat.end();
        }
        line_after_tag_handling.push_str(&line[last_pos..]);

        // 2. Remove Glyph words from line_after_tag_handling
        let mut line_after_glyph_removal = String::new();
        last_pos = 0;
        for mat in GLYPH_WORD_REGEX.find_iter(&line_after_tag_handling) {
            line_after_glyph_removal.push_str(&line_after_tag_handling[last_pos..mat.start()]);
            // Glyph word removed; add its non-whitespace chars to buffer
            for char_in_glyph in mat.as_str().chars() {
                if !char_in_glyph.is_whitespace() {
                    current_line_removed_chars_buffer.push(char_in_glyph);
                }
            }
            last_pos = mat.end();
        }
        line_after_glyph_removal.push_str(&line_after_tag_handling[last_pos..]);

        // 3. Remove unusual characters not in allowed_chars from line_after_glyph_removal
        for ch in line_after_glyph_removal.chars() {
            if unusual_chars_set.contains(&ch) && !allowed_chars.contains(&ch) {
                // Unusual char removed; add if non-whitespace to buffer
                if !ch.is_whitespace() {
                    current_line_removed_chars_buffer.push(ch);
                }
                // Do not push 'ch' to processed_line_segment
            } else {
                processed_line_segment.push(ch);
            }
        }
        
        // Declare and assign here, its value is per-line.
        let removed_chars_on_line_for_comment_decision = current_line_removed_chars_buffer.chars().count();

        // 4. Comment Insertion Logic for the current line
        if !processed_line_segment.trim().is_empty() {
            // Line has content after cleaning
            if removed_chars_on_line_for_comment_decision >= MIN_CHARS_FOR_COMMENT {
                cleaned_output.push_str(processed_line_segment.trim_end());
                cleaned_output.push(' ');
                cleaned_output.push_str(TEXT_MISSING_COMMENT);
            } else {
                cleaned_output.push_str(&processed_line_segment);
            }
        } else {
            // Line is empty or only whitespace after cleaning
            if removed_chars_on_line_for_comment_decision >= MIN_CHARS_FOR_COMMENT && line.chars().any(|c| !c.is_whitespace()) {
                // Original line had content, and enough was removed to empty it
                cleaned_output.push_str(TEXT_MISSING_COMMENT);
            } else {
                // Original line was already empty/whitespace, or not enough removed to warrant comment on emptied line
                cleaned_output.push_str(&processed_line_segment); // Append the (empty) processed line
            }
        }
        cleaned_output.push('\n'); // Add newline after each processed line
    }

    // Remove last newline if original text didn't have one and was not empty
    if !text.is_empty() && text.ends_with('\n') {
        cleaned_output
    } else {
        cleaned_output.trim_end_matches('\n').to_string()
    }
}

#[pyfunction]
#[pyo3(signature = (input_path, scripts_to_keep, output_path = None))]
fn process_file(
    input_path: &str, 
    scripts_to_keep: Vec<String>,
    output_path: Option<&str>
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
fn clean_text(text: &str, scripts_to_keep: Vec<String>) -> PyResult<String> {
    // --- Build AllowedChars Set for this call --- (This part is specific to the PyO3 wrapper)
    let mut current_allowed_chars = HashSet::new();
    for script_key in &scripts_to_keep {
        if let Some(script_set) = SCRIPT_SETS.get(script_key) {
            current_allowed_chars.extend(script_set);
        } else {
            // Optionally, could return PyValueError::new_err here if strict script key checking is desired.
            // For now, unknown keys are ignored, aligning with some existing behavior.
        }
    }
    // Call the core internal logic
    let result_string = _internal_core_clean_text_logic(text, &current_allowed_chars);
    Ok(result_string)
}

#[pyfunction]
fn list_available_scripts() -> PyResult<Vec<String>> {
    Ok(SCRIPT_SETS.keys()
        .filter(|&k| k != "unusual") // Don't expose the unusual set as keepable
        .cloned()
        .collect())
}

#[pyfunction]
fn process_directory_native(
    py: Python,
    input_dir_str: &str,
    output_dir_str: &str,
    scripts_to_keep: Vec<String>,
    num_threads: usize,
) -> PyResult<PyObject> {
    let input_path = Path::new(input_dir_str);
    let output_path = Path::new(output_dir_str);

    // --- Validate input and output paths ---
    if !input_path.is_dir() {
        return Err(PyValueError::new_err(format!(
            "Input path is not a directory: {}", input_dir_str
        )));
    }
    if !output_path.exists() {
        fs::create_dir_all(output_path).map_err(|e| {
            PyValueError::new_err(format!(
                "Failed to create output directory {}: {}", output_dir_str, e
            ))
        })?;
    } else if !output_path.is_dir() {
        return Err(PyValueError::new_err(format!(
            "Output path exists but is not a directory: {}", output_dir_str
        )));
    }

    // --- Collect markdown files ---
    let md_files: Vec<PathBuf> = WalkDir::new(input_path)
        .into_iter()
        .filter_map(Result::ok)
        .filter(|e| e.path().is_file() && e.path().extension().map_or(false, |ext| ext == "md"))
        .map(|e| e.path().to_path_buf())
        .collect();

    if md_files.is_empty() {
        let results = PyDict::new(py);
        results.set_item("status", "success")?;
        results.set_item("message", "No markdown files found in input directory.")?;
        results.set_item("files_processed", 0)?;
        return Ok(results.into());
    }

    // --- Prepare AllowedChars set (once) ---
    let mut allowed_chars = HashSet::new();
    for script_key in &scripts_to_keep {
        if let Some(script_set) = SCRIPT_SETS.get(script_key) {
            allowed_chars.extend(script_set);
        }
        // Optionally log unknown script keys if necessary
    }
    // Clone for use in parallel threads. Arc might be better if it's very large and construction is expensive.
    let allowed_chars_arc = Arc::new(allowed_chars);
    // let scripts_to_keep_arc = Arc::new(scripts_to_keep.clone()); // No longer needed

    // --- Configure Rayon Thread Pool ---
    let mut builder = ThreadPoolBuilder::new();
    if num_threads > 0 {
        builder = builder.num_threads(num_threads);
    }
    let pool = builder.build().map_err(|e| PyValueError::new_err(format!("Failed to build thread pool: {}", e)))?;

    // --- Parallel Processing with Rayon ---
    let files_processed_count = Arc::new(Mutex::new(0_usize));
    let files_error_count = Arc::new(Mutex::new(0_usize));

    pool.install(|| {
        md_files.par_iter().for_each(|md_file_path| {
            let local_allowed_chars = Arc::clone(&allowed_chars_arc);
            // let local_scripts_to_keep = Arc::clone(&scripts_to_keep_arc); // No longer needed

            match fs::read_to_string(md_file_path) {
                Ok(content) => {
                    // _internal_core_clean_text_logic now only takes content and allowed_chars
                    let cleaned_content = _internal_core_clean_text_logic(&content, &local_allowed_chars);
                    
                    // Construct output path, preserving relative structure
                    let relative_path = md_file_path.strip_prefix(input_path).unwrap_or(md_file_path);
                    let target_file_path = output_path.join(relative_path);

                    if let Some(parent_dir) = target_file_path.parent() {
                        if !parent_dir.exists() {
                            if let Err(_e) = fs::create_dir_all(parent_dir) {
                                // Log error or increment error counter for this file
                                *files_error_count.lock().unwrap() += 1;
                                return;
                            }
                        }
                    }

                    match fs::write(&target_file_path, cleaned_content) {
                        Ok(_) => {
                            *files_processed_count.lock().unwrap() += 1;
                        }
                        Err(_e) => {
                            // Log error or increment error counter for this file
                            *files_error_count.lock().unwrap() += 1;
                        }
                    }
                }
                Err(_e) => {
                    // Log error reading file or increment error counter
                    *files_error_count.lock().unwrap() += 1;
                }
            }
        });
    });

    let final_processed_count = *files_processed_count.lock().unwrap();
    let final_error_count = *files_error_count.lock().unwrap();

    let results = PyDict::new(py);
    results.set_item("status", "success")?;
    results.set_item("message", format!("Processed {} files. Errors on {} files.", final_processed_count, final_error_count))?;
    results.set_item("files_processed", final_processed_count)?;
    results.set_item("files_with_errors", final_error_count)?;
    results.set_item("total_files_found", md_files.len())?;
    Ok(results.into())
}

// --- Malformed Table Detection --- //

#[pyclass]
#[derive(Debug, Clone)]
struct TableIssue {
    #[pyo3(get)]
    line_number: usize,
    #[pyo3(get)]
    description: String,
    #[pyo3(get)]
    expected_columns: Option<usize>,
    #[pyo3(get)]
    found_columns: Option<usize>,
}

#[pymethods]
impl TableIssue {
    #[new]
    fn new(line_number: usize, description: String, expected_columns: Option<usize>, found_columns: Option<usize>) -> Self {
        TableIssue { line_number, description, expected_columns, found_columns }
    }

    fn __repr__(&self) -> String {
        format!(
            "TableIssue(line: {}, desc: '{}', expected: {:?}, found: {:?})",
            self.line_number,
            self.description,
            self.expected_columns,
            self.found_columns
        )
    }
}

#[pyfunction]
fn detect_malformed_tables(_py: Python, markdown_text: &str) -> PyResult<Vec<Py<TableIssue>>> {
    let mut issues: Vec<Py<TableIssue>> = Vec::new();
    let lines: Vec<&str> = markdown_text.lines().collect();

    // Placeholder for logic to iterate through lines, identify tables,
    // and detect malformations.
    // For now, let's add a dummy issue if we see a line that looks like a table separator
    // just to test the structure.
    for (i, line) in lines.iter().enumerate() {
        if line.contains("|---") || line.contains("|------") {
            // This is a very naive check, just for demonstration
            let issue = Py::new(_py, TableIssue::new(
                i + 1, // 1-based line number
                "Potential table separator found (naive check)".to_string(),
                None,
                None
            ))?;
            issues.push(issue);
        }
    }

    Ok(issues)
}

/// A Python module implemented in Rust.
#[pymodule]
fn text_cleaner_rs(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(analyze_text, m)?)?;
    m.add_function(wrap_pyfunction!(clean_text, m)?)?;
    m.add_function(wrap_pyfunction!(process_file, m)?)?;
    m.add_function(wrap_pyfunction!(list_available_scripts, m)?)?;
    m.add_function(wrap_pyfunction!(process_directory_native, m)?)?;
    m.add_function(wrap_pyfunction!(detect_malformed_tables, m)?)?;
    m.add_class::<TableIssue>()?;
    Ok(())
}
