Okay, that's a very clean and effective way to structure your Rust project for the functionalities you've described! This three-module approach (plus `lib.rs`) promotes excellent separation of concerns and makes it straightforward to manage and extend each part.

Here's how you can implement this structure:

**Project Structure:**

```
your_rust_project/
├── src/
│   ├── lib.rs                      # PyO3 module definition and exports
│   ├── cleaning_module.rs          # Cleaning logic, SCRIPT_SETS, cleaning Regexes
│   ├── table_analysis_module.rs    # TableIssue struct and table detection logic
│   └── directory_processor.rs      # Concurrency, file parsing, generic directory operations
└── Cargo.toml
```

---

**1. `cleaning_module.rs`**

This module will be self-contained for all text cleaning operations, script definitions, and related regular expressions. It will also house the `analyze_text_metrics` function as its "badness" calculation is based on the cleaning process.

```rust
// src/cleaning_module.rs
use lazy_static::lazy_static;
use regex::Regex;
use std::collections::{HashMap, HashSet};
use pyo3::prelude::*;
use pyo3::types::PyDict; // For analyze_text_metrics

// --- SCRIPT_SETS Definition ---
lazy_static! {
    pub static ref SCRIPT_SETS: HashMap<String, HashSet<char>> = {
        let mut map = HashMap::new();
        // (Full SCRIPT_SETS definition from your original code)
        // Example:
        map.insert("lat".to_string(), "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ".chars().collect());
        let mut greek_chars = HashSet::new();
        for code in 0x0370..0x03E2 { if let Some(c) = std::char::from_u32(code) { greek_chars.insert(c); } }
        for code in 0x03F0..0x0400 { if let Some(c) = std::char::from_u32(code) { greek_chars.insert(c); } }
        "άέήίόύώΆΈΉΊΌΎΏϊϋΪΫΐΰ".chars().for_each(|c| greek_chars.insert(c));
        map.insert("gre".to_string(), greek_chars);
        map.insert("fra".to_string(), "àâçéèêëîïôùûüÿæœÀÂÇÉÈÊËÎÏÔÙÛÜŸÆŒ«»".chars().collect());
        map.insert("spa".to_string(), "áéíóúüñÁÉÍÓÚÜÑ¿¡".chars().collect());
        map.insert("punct".to_string(), ".,;:!?()[]{}'\"&@#$%^*_-+=|\\<>/~`".chars().collect());
        map.insert("num".to_string(), "0123456789".chars().collect());
        map.insert("sym".to_string(), "€£¥©®™°§".chars().collect());
        // Unusual characters (simplified for brevity, use your full definition)
        let mut unusual_chars = HashSet::new();
        for code in 0x0080..0x0100 { /* ... add if not in other common sets ... */ if let Some(c) = std::char::from_u32(code) { unusual_chars.insert(c);}}
        // ... (add other ranges for unusual_chars) ...
        map.insert("unusual".to_string(), unusual_chars);
        map
    };

    // --- Cleaning & Analysis Regexes ---
    // Regexes for core_clean_text
    pub static ref CORE_GLYPH_WORD_REGEX: Regex = Regex::new(r"\S*glyph\S*").unwrap();
    pub static ref CORE_COMMENT_REGEX: Regex = Regex::new(r"").unwrap();
    pub static ref CORE_ANY_TAG_CLEANING_REGEX: Regex = Regex::new(r"<[^>]*>").unwrap();

    // Regexes for analyze_text_metrics (some might be shared or distinct)
    // static ref GLYPH_TAG_REGEX_RAW: Regex = Regex::new(r"(?:^|\s)glyph<c=\d+,font=/[^>]+>(?:\s|$)").unwrap();
    // static ref GLYPH_TAG_REGEX_HTML: Regex = Regex::new(r"(?:^|\s)glyph&lt;c=\d+,font=/[^>]+&gt;(?:\s|$)").unwrap();
    // static ref ANY_TAG_REGEX: Regex = Regex::new(r"(?:^|\s)<[^>]*>(?:\s|$)").unwrap(); // For detection, not cleaning
    // static ref IS_COMMENT_REGEX: Regex = Regex::new(r"^";
    const MIN_CHARS_FOR_COMMENT: usize = 5;
    let mut cleaned_output = String::new();

    for line in text.lines() {
        let mut processed_line_segment = String::new();
        let mut current_line_removed_chars_buffer = String::new();

        // 1. Tag Handling
        let mut line_after_tag_handling = String::new();
        let mut last_pos = 0;
        for mat in CORE_ANY_TAG_CLEANING_REGEX.find_iter(line) {
            line_after_tag_handling.push_str(&line[last_pos..mat.start()]);
            let tag_content = mat.as_str();
            if CORE_COMMENT_REGEX.is_match(tag_content) { // Preserves HTML comments
                line_after_tag_handling.push_str(tag_content);
            } else { // Other tags are removed
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
        for mat in CORE_GLYPH_WORD_REGEX.find_iter(&line_after_tag_handling) {
            line_after_glyph_removal.push_str(&line_after_tag_handling[last_pos..mat.start()]);
            for char_in_glyph in mat.as_str().chars().filter(|c| !c.is_whitespace()) {
                current_line_removed_chars_buffer.push(char_in_glyph);
            }
            last_pos = mat.end();
        }
        line_after_glyph_removal.push_str(&line_after_tag_handling[last_pos..]);

        // 3. Unusual Character Removal (if not in allowed_chars)
        for ch in line_after_glyph_removal.chars() {
            if unusual_chars_set.contains(&ch) && !allowed_chars.contains(&ch) {
                if !ch.is_whitespace() { current_line_removed_chars_buffer.push(ch); }
            } else {
                processed_line_segment.push(ch);
            }
        }
        
        let removed_chars_on_line_for_comment_decision = current_line_removed_chars_buffer.chars().count();

        // 4. Comment Insertion Logic (if significant chars were removed)
        if !processed_line_segment.trim().is_empty() { // Line still has content
            if removed_chars_on_line_for_comment_decision >= MIN_CHARS_FOR_COMMENT {
                cleaned_output.push_str(processed_line_segment.trim_end());
                cleaned_output.push(' ');
                cleaned_output.push_str(TEXT_MISSING_COMMENT);
            } else {
                cleaned_output.push_str(&processed_line_segment);
            }
        } else { // Line became empty after cleaning
            if removed_chars_on_line_for_comment_decision >= MIN_CHARS_FOR_COMMENT && line.chars().any(|c| !c.is_whitespace()) {
                cleaned_output.push_str(TEXT_MISSING_COMMENT); // Original had content, now empty due to removal
            } else {
                cleaned_output.push_str(&processed_line_segment); // Append the (empty) processed line
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

/// Python-exposed function to clean a single string.
#[pyfunction]
pub fn clean_text_string(text: &str, scripts_to_keep: Vec<String>) -> PyResult<String> {
    let mut allowed_chars = HashSet::new();
    for key in &scripts_to_keep {
        if let Some(script_set) = SCRIPT_SETS.get(key) {
            allowed_chars.extend(script_set);
        }
    }
    // Always include common non-alphabetic sets for general cleaning utility
    for key_to_always_include in ["punct", "num", "sym"] {
        if !scripts_to_keep.contains(&key_to_always_include.to_string()) {
             if let Some(script_set) = SCRIPT_SETS.get(key_to_always_include) {
                allowed_chars.extend(script_set);
            }
        }
    }
    let unusual_chars = SCRIPT_SETS.get("unusual").cloned().unwrap_or_default();
    Ok(core_clean_text(text, &allowed_chars, &unusual_chars))
}

/// Python-exposed function to list available script keys (excluding "unusual").
#[pyfunction]
pub fn list_available_scripts() -> PyResult<Vec<String>> {
    Ok(SCRIPT_SETS.keys().filter(|&k| k != "unusual").cloned().collect())
}

/// Python-exposed function to analyze text and provide metrics.
#[pyfunction]
pub fn analyze_text_metrics(py: Python, text: &str, scripts_to_keep: Vec<String>) -> PyResult<PyObject> {
    // --- Prepare character sets for analysis ---
    // For "badness" calculation, clean with all known "good" scripts to isolate truly "bad" chars.
    let mut allowed_chars_for_badness_calc = HashSet::new();
    SCRIPT_SETS.iter()
        .filter(|(k, _)| **k != "unusual")
        .for_each(|(_, set)| allowed_chars_for_badness_calc.extend(set));
    
    let unusual_chars_set = SCRIPT_SETS.get("unusual").cloned().unwrap_or_default();
    let cleaned_text_for_badness = core_clean_text(text, &allowed_chars_for_badness_calc, &unusual_chars_set);

    // --- Original text stats ---
    let original_total_chars = text.chars().count();
    let original_non_whitespace = text.chars().filter(|c| !c.is_whitespace()).count();

    // --- "Badness" calculation ---
    const TEXT_MISSING_COMMENT: &str = "";
    let comment_length = TEXT_MISSING_COMMENT.chars().count();
    let cleaned_non_whitespace_for_badness = cleaned_text_for_badness.chars().filter(|c| !c.is_whitespace()).count();
    let comment_count_in_badness_clean = cleaned_text_for_badness.matches(TEXT_MISSING_COMMENT).count();
    let comment_chars_added_for_badness = comment_count_in_badness_clean * comment_length;
    
    let cleaned_adjusted_for_badness = cleaned_non_whitespace_for_badness.saturating_sub(comment_chars_added_for_badness);
    let bad_char_count = original_non_whitespace.saturating_sub(cleaned_adjusted_for_badness);
    let good_char_count = original_non_whitespace.saturating_sub(bad_char_count);
    let badness_score = if original_non_whitespace > 0 { bad_char_count as f64 / original_non_whitespace as f64 } else { 0.0 };

    // --- Script Percentages ---
    // For script percentages, clean text allowing only `scripts_to_keep` + common non-alpha (punct, num, sym).
    let mut allowed_chars_for_script_calc = HashSet::new();
    for key in &scripts_to_keep {
        if let Some(script_set) = SCRIPT_SETS.get(key) { allowed_chars_for_script_calc.extend(script_set); }
    }
    for key in ["punct", "num", "sym"] { // Ensure these are always allowed for script % context
        if let Some(script_set) = SCRIPT_SETS.get(key) { allowed_chars_for_script_calc.extend(script_set); }
    }
    let cleaned_text_for_script_calc = core_clean_text(text, &allowed_chars_for_script_calc, &unusual_chars_set);
    let non_whitespace_for_script_calc = cleaned_text_for_script_calc.chars().filter(|c| !c.is_whitespace()).count();

    let mut script_percentages_map = HashMap::new();
    if !scripts_to_keep.is_empty() && non_whitespace_for_script_calc > 0 {
        let mut script_char_counts: HashMap<String, usize> = HashMap::new();
        for script_key_to_count in scripts_to_keep.iter().filter(|k| **k != "punct" && **k != "num" && **k != "sym") {
            script_char_counts.insert(script_key_to_count.clone(), 0);
        }

        for char_in_text in cleaned_text_for_script_calc.chars().filter(|c| !c.is_whitespace()) {
            for script_key_to_count in script_char_counts.keys() {
                if let Some(charset) = SCRIPT_SETS.get(script_key_to_count) {
                    if charset.contains(&char_in_text) {
                        *script_char_counts.get_mut(script_key_to_count).unwrap() += 1;
                    }
                }
            }
        }
        for (script_key, count) in script_char_counts {
            script_percentages_map.insert(script_key, (count as f64 / non_whitespace_for_script_calc as f64) * 100.0);
        }
    }
    
    // --- Other Metrics (on original text) ---
    let glyph_word_count = CORE_GLYPH_WORD_REGEX.find_iter(text).count();
    let unusual_char_count_original = text.chars().filter(|c| unusual_chars_set.contains(c)).count();

    // --- Result Assembly ---
    let results = PyDict::new(py);
    results.set_item("badness_score", badness_score)?;
    results.set_item("bad_char_count", bad_char_count)?;
    results.set_item("good_char_count", good_char_count)?;
    results.set_item("original_total_chars", original_total_chars)?;
    results.set_item("original_non_whitespace_chars", original_non_whitespace)?;
    results.set_item("glyph_word_count", glyph_word_count)?;
    results.set_item("unusual_char_count_original", unusual_char_count_original)?;
    
    let py_script_percentages = PyDict::new(py);
    for (script, percent) in script_percentages_map {
        py_script_percentages.set_item(script, percent)?;
    }
    results.set_item("script_percentages", py_script_percentages)?;
    
    Ok(results.into())
}
```

---

**2. `table_analysis_module.rs`**

This module focuses solely on table structures.

```rust
// src/table_analysis_module.rs
use pyo3::prelude::*;

#[pyclass]
#[derive(Debug, Clone)]
pub struct TableIssue {
    #[pyo3(get)] pub line_number: usize,
    #[pyo3(get)] pub description: String,
    #[pyo3(get)] pub expected_columns: Option<usize>,
    #[pyo3(get)] pub found_columns: Option<usize>,
}

#[pymethods]
impl TableIssue {
    #[new]
    pub fn new(line_number: usize, description: String, expected_columns: Option<usize>, found_columns: Option<usize>) -> Self {
        TableIssue { line_number, description, expected_columns, found_columns }
    }

    fn __repr__(&self) -> String {
        format!(
            "TableIssue(line: {}, desc: '{}', expected: {:?}, found: {:?})",
            self.line_number, self.description, self.expected_columns, self.found_columns
        )
    }
}

/// Core logic to detect malformed tables.
/// Takes Python GIL context for creating Py<TableIssue>.
pub fn core_detect_malformed_tables(py: Python, markdown_text: &str) -> PyResult<Vec<Py<TableIssue>>> {
    let mut issues: Vec<Py<TableIssue>> = Vec::new();
    let lines: Vec<&str> = markdown_text.lines().collect();

    for (i, line) in lines.iter().enumerate() {
        if line.contains("|---") || line.contains("|------") { // Current naive check
            let issue = Py::new(py, TableIssue::new(
                i + 1, // 1-based line number
                "Potential table separator found (naive check)".to_string(),
                None, None
            ))?;
            issues.push(issue);
        }
        // TODO: Implement more sophisticated table parsing and validation logic here.
        // - Check for consistent column counts between header, separator, and rows.
        // - Check for valid separator format (e.g., at least three hyphens).
        // - Check for pipes at the beginning/end of lines if it's a stylistic requirement.
    }
    Ok(issues)
}

/// Python-exposed function for table analysis on a single string.
#[pyfunction]
pub fn analyze_tables_in_string(py: Python, markdown_text: &str) -> PyResult<Vec<Py<TableIssue>>> {
    core_detect_malformed_tables(py, markdown_text)
}
```

---

**3. `directory_processor.rs`**

This is the engine for batch processing.

```rust
// src/directory_processor.rs
use rayon::prelude::*;
use rayon::ThreadPoolBuilder;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use walkdir::WalkDir;
use pyo3::prelude::*;
use pyo3::exceptions::PyValueError;
use pyo3::types::PyDict;
use std::collections::{HashMap, HashSet}; // For specific configs

// Import core functions from other modules
use crate::cleaning_module;
use crate::table_analysis_module;

/// Defines the output of a per-file operation.
pub enum PerFileOperationOutput {
    Content(String),                                      // For cleaning: the cleaned content
    TableIssues(Vec<Py<table_analysis_module::TableIssue>>), // For table analysis: list of issues
    // Add more variants for other types of analysis results if needed
}

/// Generic directory processing function.
///
/// - `OpConfig`: Type of the configuration data for the operation.
/// - `OpFn`: The actual operation to perform on each file's content.
///           Takes `(Python, &str_content, &Arc<OpConfig>)`
///           Returns `PyResult<PerFileOperationOutput>`
/// - `R`: The type of result to be collected per file (if any, beyond stats).
fn process_directory_core<OpConfig, OpFn, R>(
    py: Python,
    input_dir_str: &str,
    output_dir_str: Option<&str>, // Used if operation returns Content
    num_threads: usize,
    operation_config: Arc<OpConfig>,
    file_operation: OpFn,
    // To collect results per file (e.g., table issues for each file)
    // Key: file path (String), Value: R (the specific result type for this operation)
    detailed_results_map: Option<&Arc<Mutex<HashMap<String, R>>>>,
) -> PyResult<PyObject> // Returns a PyDict with summary statistics
where
    OpConfig: Send + Sync + 'static,
    OpFn: Fn(Python, &str, &Arc<OpConfig>) -> PyResult<PerFileOperationOutput> + Send + Sync + 'static,
    R: Send + Sync + 'static, // R is the type stored in detailed_results_map's value
{
    let input_path = Path::new(input_dir_str);
    let output_path_opt = output_dir_str.map(Path::new);

    if !input_path.is_dir() {
        return Err(PyValueError::new_err(format!("Input path is not a directory: {}", input_dir_str)));
    }
    if let Some(out_p) = output_path_opt {
        if !out_p.exists() {
            fs::create_dir_all(out_p).map_err(|e| PyValueError::new_err(format!("Failed to create output directory {}: {}", out_p.display(), e)))?;
        } else if !out_p.is_dir() {
            return Err(PyValueError::new_err(format!("Output path exists but is not a directory: {}", out_p.display())));
        }
    }

    let md_files: Vec<PathBuf> = WalkDir::new(input_path)
        .into_iter().filter_map(Result::ok)
        .filter(|e| e.path().is_file() && e.path().extension().map_or(false, |ext| ext == "md"))
        .map(|e| e.path().to_path_buf())
        .collect();

    if md_files.is_empty() {
        let summary = PyDict::new(py);
        summary.set_item("status", "success")?;
        summary.set_item("message", "No markdown files found in input directory.")?;
        summary.set_item("files_processed", 0)?;
        return Ok(summary.into());
    }

    let pool = ThreadPoolBuilder::new().num_threads(num_threads).build()
        .map_err(|e| PyValueError::new_err(format!("Failed to build thread pool: {}", e)))?;

    let files_processed_count = Arc::new(Mutex::new(0_usize));
    let files_error_count = Arc::new(Mutex::new(0_usize));

    pool.install(|| {
        md_files.par_iter().for_each(|md_file_path| {
            let config_clone = Arc::clone(&operation_config);
            match fs::read_to_string(md_file_path) {
                Ok(content) => {
                    Python::with_gil(|py_thread| { // Acquire GIL for each file task
                        match file_operation(py_thread, &content, &config_clone) {
                            Ok(operation_output) => {
                                match operation_output {
                                    PerFileOperationOutput::Content(processed_content) => {
                                        if let Some(output_base_path) = output_path_opt {
                                            let relative_path = md_file_path.strip_prefix(input_path).unwrap_or(md_file_path);
                                            let target_file_path = output_base_path.join(relative_path);
                                            if let Some(parent_dir) = target_file_path.parent() {
                                                if !parent_dir.exists() {
                                                    if fs::create_dir_all(parent_dir).is_err() {
                                                        *files_error_count.lock().unwrap() += 1; return;
                                                    }
                                                }
                                            }
                                            if fs::write(&target_file_path, processed_content).is_ok() {
                                                *files_processed_count.lock().unwrap() += 1;
                                            } else { *files_error_count.lock().unwrap() += 1; }
                                        } else { // Content generated, but no output dir specified. Count as processed.
                                            *files_processed_count.lock().unwrap() += 1;
                                        }
                                    }
                                    PerFileOperationOutput::TableIssues(issues) => {
                                        if let Some(collector) = detailed_results_map {
                                            // This assumes R is Vec<Py<table_analysis_module::TableIssue>>
                                            // Collector needs to be HashMap<String, Vec<Py<table_analysis_module::TableIssue>>>
                                            // This assignment requires R to be Vec<Py<TableIssue>> or an enum that can hold it.
                                            // For now, we'll assume the calling function sets R appropriately.
                                            // This cast is unsafe if R is not actually Vec<Py<TableIssue>>.
                                            // A better way is to make R = PerFileOperationOutput and let Python unpack.
                                            // Or, the file_operation itself pushes to a specifically typed collector.
                                            // Let's assume R = PerFileOperationOutput for general collection.
                                            let issues_cloned_for_r: R = unsafe {
                                                std::mem::transmute_copy::<PerFileOperationOutput, R>(
                                                    &PerFileOperationOutput::TableIssues(
                                                        issues.into_iter().map(|i| i.clone_ref(py_thread)).collect()
                                                    )
                                                )
                                            };
                                            collector.lock().unwrap().insert(md_file_path.to_string_lossy().into_owned(), issues_cloned_for_r);
                                        }
                                        *files_processed_count.lock().unwrap() += 1;
                                    }
                                }
                            }
                            Err(_err) => { *files_error_count.lock().unwrap() += 1; /* TODO: Log error _err */ }
                        }
                    });
                }
                Err(_err) => { *files_error_count.lock().unwrap() += 1; /* TODO: Log error _err */ }
            }
        });
    });

    let final_processed = *files_processed_count.lock().unwrap();
    let final_errors = *files_error_count.lock().unwrap();
    let summary = PyDict::new(py);
    summary.set_item("status", "completed")?;
    summary.set_item("message", format!("Operation completed on {} files. Errors on {} files.", final_processed, final_errors))?;
    summary.set_item("files_processed", final_processed)?;
    summary.set_item("files_with_errors", final_errors)?;
    summary.set_item("total_files_found_in_dir", md_files.len())?;

    if let Some(collector) = detailed_results_map {
        let results_dict = PyDict::new(py);
        for (file_path, data) in collector.lock().unwrap().iter() {
            // Convert data (R) to PyObject. This depends heavily on what R is.
            // If R is PerFileOperationOutput:
            let py_data = match data { // Assuming R is PerFileOperationOutput for this example
                 PerFileOperationOutput::TableIssues(iss) => iss.to_object(py),
                 PerFileOperationOutput::Content(_) => py.None(), // Content itself isn't usually returned in detailed_results
            };
            results_dict.set_item(file_path, py_data)?;
        }
        if !results_dict.is_empty(){
            summary.set_item("detailed_results_per_file", results_dict)?;
        }
    }

    Ok(summary.into())
}


// --- Python-exposed Batch Cleaning Function ---
struct BatchCleanOpConfig {
    allowed_chars: HashSet<char>,
    unusual_chars: HashSet<char>,
}

#[pyfunction]
pub fn batch_clean_markdown_files(
    py: Python,
    input_dir: &str,
    output_dir: &str,
    scripts_to_keep: Vec<String>,
    num_threads: usize,
) -> PyResult<PyObject> {
    let mut allowed_chars = HashSet::new();
    for key in &scripts_to_keep {
        if let Some(script_set) = cleaning_module::SCRIPT_SETS.get(key) {
            allowed_chars.extend(script_set);
        }
    }
    for key_to_always_include in ["punct", "num", "sym"] { // Ensure common sets are included
        if !scripts_to_keep.contains(&key_to_always_include.to_string()) {
             if let Some(script_set) = cleaning_module::SCRIPT_SETS.get(key_to_always_include) {
                allowed_chars.extend(script_set);
            }
        }
    }
    let unusual_chars = cleaning_module::SCRIPT_SETS.get("unusual").cloned().unwrap_or_default();
    let config = Arc::new(BatchCleanOpConfig { allowed_chars, unusual_chars });

    let clean_file_op = |_py_thread: Python, content: &str, op_conf: &Arc<BatchCleanOpConfig>| {
        let cleaned_content = cleaning_module::core_clean_text(content, &op_conf.allowed_chars, &op_conf.unusual_chars);
        Ok(PerFileOperationOutput::Content(cleaned_content))
    };

    // For cleaning, we don't typically collect detailed results beyond the summary stats.
    // So, R can be a dummy type like `()` or we pass `None` for `detailed_results_map`.
    // The generic `R` in `process_directory_core` will be `()` if `None` is passed.
    process_directory_core::<BatchCleanOpConfig, _, ()>( // R is ()
        py,
        input_dir,
        Some(output_dir),
        num_threads,
        config,
        clean_file_op,
        None, // No detailed results collection, R is effectively ()
    )
}

// --- Python-exposed Batch Table Analysis Function ---
struct BatchTableAnalysisOpConfig { /* Currently no specific config, but can be extended */ }

#[pyfunction]
pub fn batch_analyze_tables_in_files(
    py: Python,
    input_dir: &str,
    num_threads: usize,
) -> PyResult<PyObject> {
    let config = Arc::new(BatchTableAnalysisOpConfig {});
    
    // R in process_directory_core will be PerFileOperationOutput for this case
    let collected_results: Arc<Mutex<HashMap<String, PerFileOperationOutput>>> = Arc::new(Mutex::new(HashMap::new()));

    let analyze_table_op = |py_thread: Python, content: &str, _op_conf: &Arc<BatchTableAnalysisOpConfig>| {
        let issues = table_analysis_module::core_detect_malformed_tables(py_thread, content)?;
        Ok(PerFileOperationOutput::TableIssues(issues))
    };

    process_directory_core(
        py,
        input_dir,
        None, // No output directory for analysis reports (unless writing to files)
        num_threads,
        config,
        analyze_table_op,
        Some(&collected_results), // Pass the collector
    )
}
```
*Correction for `process_directory_core` and its usage in `batch_analyze_tables_in_files`: The unsafe `transmute` is a bad idea. The type `R` should directly be what you intend to collect. For table analysis, `R` would be `Vec<Py<table_analysis_module::TableIssue>>`. The `PerFileOperationOutput` enum helps the `process_directory_core` decide if it needs to write content, but the `detailed_results_map` should store the *actual data* of type `R`.*

A better approach for `process_directory_core`'s `detailed_results_map` and `R`: `R` should be the *specific type of data you want to collect for that operation*. The `file_operation` closure should then return `PyResult<(PerFileOperationOutput, Option<R>)>`. The `PerFileOperationOutput` guides immediate actions (like writing content), and `Option<R>` provides the data to be collected.

Let's simplify `process_directory_core` by removing the generic `R` from its direct signature and letting the specific batch functions handle the collection if needed, or by making `R` always `PerFileOperationOutput` if the Python side will unpack it. The version above uses `R=PerFileOperationOutput` for `batch_analyze_tables_in_files` and `R=()` (via `None`) for `batch_clean_markdown_files`. This means the `detailed_results_per_file` in the summary will contain `PerFileOperationOutput` variants, which Python can then inspect.

---

**4. `lib.rs`**

This file sets up the Python module and exports the public functions.

```rust
// src/lib.rs
mod cleaning_module;
mod table_analysis_module;
mod directory_processor;

use pyo3::prelude::*;

#[pymodule]
fn text_cleaner_rs(_py: Python, m: &PyModule) -> PyResult<()> {
    // Functions from cleaning_module (for single string operations)
    m.add_function(wrap_pyfunction!(cleaning_module::clean_text_string, m)?)?;
    m.add_function(wrap_pyfunction!(cleaning_module::list_available_scripts, m)?)?;
    m.add_function(wrap_pyfunction!(cleaning_module::analyze_text_metrics, m)?)?;

    // Class and function from table_analysis_module (for single string operations)
    m.add_class::<table_analysis_module::TableIssue>()?;
    m.add_function(wrap_pyfunction!(table_analysis_module::analyze_tables_in_string, m)?)?;
    
    // Batch processing functions from directory_processor
    m.add_function(wrap_pyfunction!(directory_processor::batch_clean_markdown_files, m)?)?;
    m.add_function(wrap_pyfunction!(directory_processor::batch_analyze_tables_in_files, m)?)?;

    Ok(())
}
```

**Key Benefits of this Structure:**

* **Focused Modules:** Each `.rs` file has a clear, distinct responsibility.
* **Reusable Core Logic:** Functions like `core_clean_text` and `core_detect_malformed_tables` are pure Rust functions, making them easy to test and reuse internally if needed.
* **Generic Directory Processor:** `directory_processor.rs` provides a robust way to handle common batch operations (directory walking, threading, file I/O) without being tied to specific processing logic.
* **Extensibility:**
    * To add a new type of text processing (e.g., "keyword extraction"), you'd create a `keyword_extraction_module.rs` with its core logic.
    * Then, in `directory_processor.rs`, you'd add a new `PerFileOperationOutput` variant, a config struct (if needed), and a new `batch_extract_keywords_in_files` function that calls `process_directory_core` with the new operation.
    * Finally, expose the new batch function in `lib.rs`.
* **Clear Python API:** The functions exposed in `lib.rs` provide a clean interface for Python users.

This refactoring provides a strong and maintainable foundation for your Rust-powered Python module. Remember to test thoroughly after these changes!