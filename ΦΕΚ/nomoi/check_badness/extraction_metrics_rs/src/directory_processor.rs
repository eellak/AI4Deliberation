use pyo3::prelude::*;
use pyo3::exceptions::PyValueError;
use pyo3::types::PyDict;
use rayon::prelude::*;
use rayon::ThreadPoolBuilder;
use std::collections::{HashSet};
use std::fs::{self};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use walkdir::WalkDir;
use csv::Writer;
use serde::Serialize;

use crate::table_analysis_module;
use crate::cleaning_module;

// Define operation output variants
pub enum PerFileOperationOutput {
    Content(String),
    TableIssues(Vec<Py<table_analysis_module::TableIssue>>),
    Empty,
}

/// Core directory processing function with concurrency support
fn process_directory_core<OpConfig, OpFn>(
    py: Python,
    input_dir_str: &str,
    output_dir_str: Option<&str>,
    num_threads: usize,
    operation_config: Arc<OpConfig>,
    file_operation: OpFn,
) -> PyResult<PyObject>
where
    OpConfig: Send + Sync + 'static,
    OpFn: Fn(Python, &str, &Arc<OpConfig>) -> PyResult<PerFileOperationOutput> + Send + Sync + 'static,
{
    println!("DEBUG: Entering process_directory_core");
    let input_path = Path::new(input_dir_str);
    let output_path_opt = output_dir_str.map(Path::new);

    if !input_path.is_dir() {
        println!("ERROR: Input path is not a directory: {}", input_dir_str);
        return Err(PyValueError::new_err(format!("Input path is not a directory: {}", input_dir_str)));
    }

    if let Some(out_p) = output_path_opt {
        if !out_p.exists() {
            println!("INFO: Creating output directory: {}", out_p.display());
            fs::create_dir_all(out_p).map_err(|e| 
                PyValueError::new_err(format!("Failed to create output directory {}: {}", out_p.display(), e)))?;
        } else if !out_p.is_dir() {
            println!("ERROR: Output path exists but is not a directory: {}", out_p.display());
            return Err(PyValueError::new_err(format!("Output path exists but is not a directory: {}", out_p.display())));
        }
    }

    // Collect markdown files
    println!("DEBUG: Collecting markdown files from: {}", input_path.display());
    let md_files: Vec<PathBuf> = WalkDir::new(input_path)
        .into_iter().filter_map(Result::ok)
        .filter(|e| e.path().is_file() && e.path().extension().is_some_and(|ext| ext == "md"))
        .map(|e| e.path().to_path_buf())
        .collect();

    println!("DEBUG: Found {} markdown files", md_files.len());

    if md_files.is_empty() {
        println!("INFO: No markdown files found in input directory");
        let summary = PyDict::new(py);
        summary.set_item("status", "success")?;
        summary.set_item("message", "No markdown files found in input directory.")?;
        summary.set_item("files_processed", 0)?;
        return Ok(summary.into());
    }

    println!("getting warmer");

    // Configure thread pool
    let thread_count = if num_threads > 0 {
        println!("counting threads");
        num_threads 
    } else { 
        // Default: use number of logical cores
        println!("using default threads");
        std::thread::available_parallelism().map(|n| n.get()).unwrap_or(4)
    };

    println!("INFO: Configuring thread pool with {} threads", thread_count);
    let pool = ThreadPoolBuilder::new()
        .num_threads(thread_count)
        .build()
        .map_err(|e| PyValueError::new_err(format!("Failed to build thread pool: {}", e)))?;

    let files_processed_count = Arc::new(Mutex::new(0_usize));
    let files_error_count = Arc::new(Mutex::new(0_usize));

    // Store a copy of values we need for later
    let input_path_copy = input_path.to_path_buf();
    let output_path_opt_copy = output_path_opt.map(|p| p.to_path_buf());

    println!("INFO: Starting parallel processing with Rayon");
    println!("INFO: Releasing the GIL before starting Rayon tasks");
    
    // Release the GIL before starting Rayon tasks to avoid deadlock
    py.allow_threads(|| {
        println!("DEBUG: Inside allow_threads, GIL is released");
        
        pool.install(|| {
            println!("DEBUG: Inside Rayon pool.install");
            
            md_files.par_iter().for_each(|md_file_path| {
                let config_clone = Arc::clone(&operation_config);
                println!("DEBUG: Processing file: {}", md_file_path.display());
                
                // Read the file content outside of the GIL
                match fs::read_to_string(md_file_path) {
                    Ok(content) => {
                        println!("DEBUG: Read {} chars from {}", content.len(), md_file_path.display());
                        
                        // Re-acquire the GIL only when needed for Python operations
                        Python::with_gil(|py_thread| {
                            println!("DEBUG: Re-acquired GIL for processing file");
                            
                            match file_operation(py_thread, &content, &config_clone) {
                                Ok(operation_output) => {
                                    match &operation_output {
                                        PerFileOperationOutput::Content(processed_content) => {
                                            println!("DEBUG: Processed content has {} chars", processed_content.len());
                                            
                                            // Release the GIL for file operations
                                            let _ = py_thread;
                                            
                                            if let Some(output_base_path) = &output_path_opt_copy {
                                                let relative_path = md_file_path.strip_prefix(&input_path_copy).unwrap_or(md_file_path);
                                                let target_file_path = output_base_path.join(relative_path);
                                                
                                                if let Some(parent_dir) = target_file_path.parent() {
                                                    if !parent_dir.exists() {
                                                        println!("DEBUG: Creating parent directory: {}", parent_dir.display());
                                                        if fs::create_dir_all(parent_dir).is_err() {
                                                            println!("ERROR: Failed to create directory: {}", parent_dir.display());
                                                            *files_error_count.lock().unwrap() += 1;
                                                            return;
                                                        }
                                                    }
                                                }
                                                
                                                println!("DEBUG: Writing to file: {}", target_file_path.display());
                                                if fs::write(&target_file_path, processed_content).is_ok() {
                                                    println!("DEBUG: Successfully wrote file: {}", target_file_path.display());
                                                    *files_processed_count.lock().unwrap() += 1;
                                                } else { 
                                                    println!("ERROR: Failed to write file: {}", target_file_path.display());
                                                    *files_error_count.lock().unwrap() += 1; 
                                                }
                                            } else {
                                                // Content generated, but no output dir specified
                                                println!("DEBUG: No output dir specified, just counting processed file");
                                                *files_processed_count.lock().unwrap() += 1;
                                            }
                                        }
                                        PerFileOperationOutput::TableIssues(_issues) => {
                                            // For TableIssues, we'll collect them after parallel processing is done
                                            println!("DEBUG: Processed table issues");
                                            *files_processed_count.lock().unwrap() += 1;
                                        },
                                        PerFileOperationOutput::Empty => {
                                            println!("DEBUG: Empty operation output");
                                            *files_processed_count.lock().unwrap() += 1;
                                        }
                                    }
                                }
                                Err(err) => { 
                                    println!("ERROR: Failed to process file: {}: {:?}", md_file_path.display(), err);
                                    *files_error_count.lock().unwrap() += 1; 
                                }
                            }
                        });
                    }
                    Err(err) => { 
                        println!("ERROR: Failed to read file: {}: {:?}", md_file_path.display(), err);
                        *files_error_count.lock().unwrap() += 1; 
                    }
                }
            });
            
            println!("DEBUG: Completed Rayon parallel processing");
        });
        
        println!("DEBUG: Exited Rayon pool.install");
    });
    
    println!("DEBUG: GIL re-acquired after Rayon processing");

    // Prepare summary
    let final_processed = *files_processed_count.lock().unwrap();
    let final_errors = *files_error_count.lock().unwrap();
    
    println!("INFO: Processing completed - {} files processed, {} errors", final_processed, final_errors);
    
    let summary = PyDict::new(py);
    summary.set_item("status", "completed")?;
    summary.set_item("message", format!("Operation completed on {} files. Errors on {} files.", final_processed, final_errors))?;
    summary.set_item("files_processed", final_processed)?;
    summary.set_item("files_with_errors", final_errors)?;
    summary.set_item("total_files_found", md_files.len())?;

    // No detailed results collection in the core function anymore
    // This is now handled in the specific batch functions

    Ok(summary.into())
}

// Configuration for batch cleaning operations
struct BatchCleanOpConfig {
    allowed_chars: HashSet<char>,
    unusual_chars: HashSet<char>,
}

// Configuration for table analysis operations
struct TableAnalysisConfig {
    // Empty configuration as we don't need special settings for table analysis
}

#[derive(Debug, Serialize)]
struct FileReportData {
    file_name: String,
    original_chars: usize,
    cleaned_chars: usize,
    removed_chars_total: usize,
    badness_score_non_ws: Option<f64>,
    badness_score_all_chars: Option<f64>,
    greek_chars_cleaned: Option<usize>,
    latin_chars_cleaned: Option<usize>,
    percentage_greek_cleaned: Option<f64>,
    percentage_latin_cleaned: Option<f64>,
    cleaned_non_whitespace_chars: Option<usize>,
    error_message: Option<String>,
}

#[pyfunction]
#[pyo3(signature = (input_dir_str, output_csv_path_str, output_dir_cleaned_files_str, scripts_to_analyze, num_threads))]
pub fn generate_analysis_report_for_directory(
    py: Python,
    input_dir_str: &str,
    output_csv_path_str: &str,
    output_dir_cleaned_files_str: Option<&str>,
    scripts_to_analyze: Vec<String>,
    num_threads: usize,
) -> PyResult<()> {
    let input_path = Path::new(input_dir_str);
    if !input_path.is_dir() {
        return Err(PyValueError::new_err(format!(
            "Input path is not a directory: {}", input_dir_str
        )));
    }

    let output_csv_path = Path::new(output_csv_path_str);
    if let Some(parent) = output_csv_path.parent() {
        fs::create_dir_all(parent).map_err(|e| {
            PyValueError::new_err(format!(
                "Failed to create output directory {}: {}",
                parent.display(),
                e
            ))
        })?;
    }
    
    let md_files: Vec<PathBuf> = WalkDir::new(input_path)
        .into_iter().filter_map(Result::ok)
        .filter(|e| e.path().is_file() && e.path().extension().is_some_and(|ext| ext == "md"))
        .map(|e| e.path().to_path_buf())
        .collect();

    if md_files.is_empty() {
        println!("INFO: No markdown files found. CSV will be empty except for headers.");
        // Create CSV with only headers if no files found
        let mut wtr = Writer::from_path(output_csv_path)
            .map_err(|e| PyValueError::new_err(format!("Failed to create CSV writer: {}", e)))?;
        wtr.write_record(["file_path", "badness_score", "greek_char_percentage", "latin_char_percentage"])
            .map_err(|e| PyValueError::new_err(format!("Failed to write CSV header: {}", e)))?;
        wtr.flush().map_err(|e| PyValueError::new_err(format!("Failed to flush CSV writer: {}", e)))?;
        return Ok(());
    }
    
    let thread_count = if num_threads > 0 { num_threads } else { std::thread::available_parallelism().map(|n| n.get()).unwrap_or(4) };
    let pool = ThreadPoolBuilder::new()
        .num_threads(thread_count)
        .build()
        .map_err(|e| PyValueError::new_err(format!("Failed to build thread pool: {}", e)))?;

    // --- Character Set Preparation ---
    let mut base_allowed_chars = HashSet::new();
    // Use scripts_to_analyze to build the initial set of allowed characters
    for key in &scripts_to_analyze {
        if let Some(script_set) = cleaning_module::SCRIPT_SETS.get(key) {
            base_allowed_chars.extend(script_set);
        }
    }
    // Ensure common scripts (punctuation, numbers, common_symbols) are always included.
    for key_str in ["punctuation", "numbers", "common_symbols"].iter() {
        let key = key_str.to_string();
        // Add common scripts if they weren't already in scripts_to_analyze (or just add them unconditionally)
        if let Some(script_set) = cleaning_module::SCRIPT_SETS.get(&key) {
            base_allowed_chars.extend(script_set);
        }
    }
    base_allowed_chars.insert(' ');
    base_allowed_chars.insert('\t');
    base_allowed_chars.insert('\n');
    
    let allowed_chars_arc = Arc::new(base_allowed_chars);
    let unusual_chars_arc = Arc::new(cleaning_module::SCRIPT_SETS.get("unusual").cloned().unwrap_or_default());

    // Scripts for which specific counts are needed (for percentages)
    // For the CSV, we specifically need Greek and Latin counts.
    // The `_scripts_for_percentage_and_specific_counts` parameter of `perform_text_analysis`
    // expects a slice of strings. We will pass ["greek", "latin"].
    // `calculate_specific_counts` being true ensures these are attempted.
    // The `SlimTextAnalysisResult` struct has specific fields for greek_char_count and latin_char_count.
    // So, we just need to ensure `calculate_specific_counts` is true.
    // The `scripts_to_analyze` argument to *this* function (`generate_analysis_report_for_directory`)
    // is primarily for constructing `allowed_chars_arc`.
    // The `perform_text_analysis` will try to populate greek/latin counts if `calculate_specific_counts` is true,
    // The `scripts_to_analyze` parameter of `perform_text_analysis` is used to decide which scripts to count.
    // let scripts_for_perform_analysis_arc = Arc::new(vec!["greek".to_string(), "latin".to_string()]); // This is unused and can be removed

    let input_path_arc = Arc::new(input_path.to_path_buf()); 
    let output_cleaned_path_arc = Arc::new(output_dir_cleaned_files_str.map(PathBuf::from));

    println!("Starting parallel analysis phase...");
    let analysis_phase_start = std::time::Instant::now();

    // Results for CSV will be collected from parallel tasks.
    let collected_report_data: Vec<FileReportData> = py.allow_threads(|| {
        pool.install(|| {
            md_files
                .par_iter()
                .filter_map(|md_file_path| {
                    let allowed_chars_thread = Arc::clone(&allowed_chars_arc);
                    let unusual_chars_thread = Arc::clone(&unusual_chars_arc);
                    let scripts_for_analysis_ref: &[String] = &scripts_to_analyze; 

                    let local_input_path_arc = Arc::clone(&input_path_arc); 
                    let local_output_cleaned_path_arc = Arc::clone(&output_cleaned_path_arc);

                    match fs::read_to_string(md_file_path) {
                        Ok(content) => {
                            let analysis_result = cleaning_module::perform_text_analysis(
                                &content,
                                &allowed_chars_thread,
                                &unusual_chars_thread,
                                scripts_for_analysis_ref,
                                true,
                                None  // min_chars_for_comment (use default in core_clean_text)
                            );

                            let removed_total_chars = analysis_result.original_total_chars.saturating_sub(analysis_result.cleaned_total_chars);

                            let mut percentage_greek_cleaned = None;
                            if let Some(count) = analysis_result.greek_char_count_after_clean {
                                let cleaned_non_whitespace_after_clean = analysis_result.cleaned_non_whitespace_chars_after_clean.unwrap_or(0);
                                if cleaned_non_whitespace_after_clean > 0 && count > 0 { // Calculate percentage only if both are positive
                                    percentage_greek_cleaned = Some(count as f64 / cleaned_non_whitespace_after_clean as f64 * 100.0);
                                } else { // Otherwise, it's 0%
                                    percentage_greek_cleaned = Some(0.0);
                                }
                            } // If count is None, percentage_greek_cleaned remains None

                            let mut percentage_latin_cleaned = None;
                            if let Some(count) = analysis_result.latin_char_count_after_clean {
                                let cleaned_non_whitespace_after_clean = analysis_result.cleaned_non_whitespace_chars_after_clean.unwrap_or(0);
                                if cleaned_non_whitespace_after_clean > 0 && count > 0 { // Calculate percentage only if both are positive
                                    percentage_latin_cleaned = Some(count as f64 / cleaned_non_whitespace_after_clean as f64 * 100.0);
                                } else { // Otherwise, it's 0%
                                    percentage_latin_cleaned = Some(0.0);
                                }
                            } // If count is None, percentage_latin_cleaned remains None

                            // Optionally save cleaned file
                            if let Some(output_base_path) = &*local_output_cleaned_path_arc {
                                let relative_path = md_file_path.strip_prefix(&*local_input_path_arc).unwrap_or(md_file_path);
                                let target_file_path = output_base_path.join(relative_path);
                                
                                if let Some(parent_dir) = target_file_path.parent() {
                                    if !parent_dir.exists() {
                                        if let Err(e) = fs::create_dir_all(parent_dir) {
                                            return Some(FileReportData {
                                                file_name: md_file_path.file_name().unwrap_or_default().to_string_lossy().into_owned(),
                                                original_chars: analysis_result.original_total_chars,
                                                cleaned_chars: analysis_result.cleaned_total_chars,
                                                removed_chars_total: removed_total_chars,
                                                badness_score_non_ws: analysis_result.badness_score_non_ws,
                                                badness_score_all_chars: analysis_result.badness_score_all_chars,
                                                greek_chars_cleaned: analysis_result.greek_char_count_after_clean,
                                                latin_chars_cleaned: analysis_result.latin_char_count_after_clean,
                                                percentage_greek_cleaned,
                                                percentage_latin_cleaned,
                                                cleaned_non_whitespace_chars: analysis_result.cleaned_non_whitespace_chars_after_clean,
                                                error_message: Some(format!("Failed to create output dir {}: {}", parent_dir.display(), e)),
                                            });
                                        }
                                    }
                                }
                                
                                if let Err(e) = fs::write(&target_file_path, &analysis_result.cleaned_text_content) {
                                    return Some(FileReportData {
                                        file_name: md_file_path.file_name().unwrap_or_default().to_string_lossy().into_owned(),
                                        original_chars: analysis_result.original_total_chars,
                                        cleaned_chars: analysis_result.cleaned_total_chars,
                                        removed_chars_total: removed_total_chars,
                                        badness_score_non_ws: analysis_result.badness_score_non_ws,
                                        badness_score_all_chars: analysis_result.badness_score_all_chars,
                                        greek_chars_cleaned: analysis_result.greek_char_count_after_clean,
                                        latin_chars_cleaned: analysis_result.latin_char_count_after_clean,
                                        percentage_greek_cleaned,
                                        percentage_latin_cleaned,
                                        cleaned_non_whitespace_chars: analysis_result.cleaned_non_whitespace_chars_after_clean,
                                        error_message: Some(format!("Failed to write cleaned file {}: {}", target_file_path.display(), e)),
                                    });
                                }
                            }

                            Some(FileReportData {
                                file_name: md_file_path.file_name().unwrap_or_default().to_string_lossy().into_owned(),
                                original_chars: analysis_result.original_total_chars,
                                cleaned_chars: analysis_result.cleaned_total_chars,
                                removed_chars_total: removed_total_chars,
                                badness_score_non_ws: analysis_result.badness_score_non_ws,
                                badness_score_all_chars: analysis_result.badness_score_all_chars,
                                greek_chars_cleaned: analysis_result.greek_char_count_after_clean,
                                latin_chars_cleaned: analysis_result.latin_char_count_after_clean,
                                percentage_greek_cleaned,
                                percentage_latin_cleaned,
                                cleaned_non_whitespace_chars: analysis_result.cleaned_non_whitespace_chars_after_clean,
                                error_message: None,
                            })
                        }
                        Err(e) => {
                            // Error reading the file
                            Some(FileReportData {
                                file_name: md_file_path.file_name().unwrap_or_default().to_string_lossy().into_owned(),
                                original_chars: 0, cleaned_chars: 0, removed_chars_total: 0, badness_score_non_ws: Some(0.0), badness_score_all_chars: Some(0.0),
                                greek_chars_cleaned: None, latin_chars_cleaned: None, 
                                percentage_greek_cleaned: None, percentage_latin_cleaned: None,
                                cleaned_non_whitespace_chars: None,
                                error_message: Some(format!("Failed to read file {}: {}", md_file_path.display(), e)),
                            })
                        }
                    }
                })
                .collect()
        })
    });

    let analysis_phase_duration = analysis_phase_start.elapsed();
    println!("Parallel analysis phase completed in: {:.2?}", analysis_phase_duration);

    // Commenting out CSV writing phase for this test
    /*
    println!("Starting CSV writing phase...");
    */
    // Restoring CSV writing phase
    println!("Starting CSV writing phase...");
    let csv_writing_start = std::time::Instant::now();

    let mut wtr = Writer::from_path(output_csv_path)
        .map_err(|e| PyValueError::new_err(format!("Failed to create CSV writer: {}", e)))?;
    
    // Updated CSV header
    wtr.write_record([
        "File Name", 
        "Badness",
        "Greek Percentage", 
        "Latin Percentage",
    ]).map_err(|e| PyValueError::new_err(format!("CSV header write error: {}", e)))?; 

    let mut sorted_report_data = collected_report_data;
    sorted_report_data.sort_by(|a, b| a.file_name.cmp(&b.file_name));

    for report_item in &sorted_report_data {
        let file_name_for_error_log = report_item.file_name.clone();
        // Updated CSV row writing
        wtr.write_record([
            report_item.file_name.clone(),
            report_item.badness_score_all_chars.map_or_else(|| "N/A".to_string(), |v| format!("{:.4}", v)),
            report_item.percentage_greek_cleaned.map_or_else(|| "N/A".to_string(), |v| format!("{:.2}%", v)),
            report_item.percentage_latin_cleaned.map_or_else(|| "N/A".to_string(), |v| format!("{:.2}%", v)),
        ]).map_err(|e| PyValueError::new_err(format!("CSV row write error for {}: {}", file_name_for_error_log, e)))?;
    }

    wtr.flush().map_err(|e| PyValueError::new_err(format!("CSV flush error: {}", e)))?;
    
    let csv_writing_duration = csv_writing_start.elapsed();
    println!("CSV writing phase completed in: {:.2?}", csv_writing_duration);
    /*
    println!("CSV writing phase was SKIPPED for this test.");
    */

    let files_processed_count = sorted_report_data.len();
    let files_that_had_read_errors_or_processing_errors = md_files.len().saturating_sub(files_processed_count);

    println!(
        "CSV report generated at: {}. Processed: {}, Errors reading files: {}",
        output_csv_path_str,
        files_processed_count,
        files_that_had_read_errors_or_processing_errors
    );

    Ok(())
}

/// Python-exposed function for batch cleaning of markdown files
#[pyfunction]
pub fn batch_clean_markdown_files(
    py: Python,
    input_dir: &str,
    output_dir: &str,
    scripts_to_keep: Vec<String>,
    num_threads: usize,
) -> PyResult<PyObject> {
    // Debug prints
    println!("INFO: Starting batch_clean_markdown_files with {} threads", num_threads);
    println!("DEBUG: Input dir: {}", input_dir);
    println!("DEBUG: Output dir: {}", output_dir);
    println!("DEBUG: Scripts to keep: {:?}", scripts_to_keep);

    // Prepare character sets for cleaning
    let mut allowed_chars = HashSet::new();
    
    // Debug print for available CPU cores
    println!("INFO: Available CPU cores: {}, using {} threads", 
             std::thread::available_parallelism().map_or(4, |n| n.get()), num_threads);
    
    // Fix script mapping to match what's in SCRIPT_SETS (lat->lat, not lat->latin)
    println!("DEBUG: Script mapping from user input: {:?}", scripts_to_keep);
    
    // Check if scripts exist and add their characters
    for key in &scripts_to_keep {
        if let Some(script_set) = cleaning_module::SCRIPT_SETS.get(key) {
            println!("DEBUG: Adding {} characters from script: {}", script_set.len(), key);
            allowed_chars.extend(script_set);
        } else {
            println!("WARNING: Script '{}' not found in SCRIPT_SETS", key);
        }
    }
    
    // Include common non-alphabetic sets if not specified - use correct keys that match SCRIPT_SETS
    let keys_to_include = ["punctuation", "numbers", "common_symbols"]; // Corrected keys
    println!("DEBUG: Also adding characters from: {:?}", keys_to_include);
    
    for key_to_always_include in keys_to_include {
        if !scripts_to_keep.contains(&key_to_always_include.to_string()) {
            if let Some(script_set) = cleaning_module::SCRIPT_SETS.get(key_to_always_include) {
                println!("DEBUG: Adding {} characters from always-included script: {}", 
                        script_set.len(), key_to_always_include);
                allowed_chars.extend(script_set);
            } else {
                println!("WARNING: Always-include script '{}' not found in SCRIPT_SETS", key_to_always_include);
            }
        }
    }

    // Add essential whitespace characters
    allowed_chars.insert(' ');
    allowed_chars.insert('\t');
    allowed_chars.insert('\n');
    println!("DEBUG: Added whitespace characters");

    let unusual_chars = cleaning_module::SCRIPT_SETS.get("unusual").cloned().unwrap_or_default();
    println!("DEBUG: Using {} unusual characters for detection", unusual_chars.len());
    println!("DEBUG: Total allowed characters: {}", allowed_chars.len());
    
    let config = Arc::new(BatchCleanOpConfig { 
        allowed_chars, 
        unusual_chars 
    });

    // Define the cleaning operation function - fix how we call core_clean_text
    let clean_file_op = |_py_thread: Python, content: &str, op_conf: &Arc<BatchCleanOpConfig>| {
        println!("DEBUG: Processing file with {} characters", content.len());
        
        let cleaned_content_tuple = cleaning_module::core_clean_text(
            content, 
            &op_conf.allowed_chars, 
            &op_conf.unusual_chars,
            None // Add missing 4th argument: min_chars_for_comment_override
        );
        
        println!("DEBUG: Cleaned content has {} characters", cleaned_content_tuple.0.len());
        Ok(PerFileOperationOutput::Content(cleaned_content_tuple.0))
    };

    // Process the directory
    println!("INFO: Starting directory processing...");
    let result = process_directory_core::<BatchCleanOpConfig, _>(
        py,
        input_dir,
        Some(output_dir),
        num_threads,
        config,
        clean_file_op
    );
    
    println!("INFO: Directory processing completed");
    result
}

/// Python-exposed function for batch table analysis of markdown files
#[pyfunction]
pub fn batch_analyze_tables_in_files(py: Python, input_dir: &str, num_threads: usize) -> PyResult<PyObject> {
    // We'll use the functions directly from table_analysis_module

    // Create an empty config
    let config = Arc::new(TableAnalysisConfig {});
    
    // Define the table analysis operation
    let analyze_table_op = |py_thread: Python, content: &str, _config: &Arc<TableAnalysisConfig>| {
        // Analyze the content for table issues
        let issues = table_analysis_module::analyze_table_file_op(py_thread, content)?;
        
        // Return the issues as part of the operation output
        if !issues.is_empty() {
            Ok(PerFileOperationOutput::TableIssues(issues))
        } else {
            Ok(PerFileOperationOutput::Empty)
        }
    };
    
    // Process the directory using the generic processor
    let result_obj = process_directory_core::<TableAnalysisConfig, _>(
        py,
        input_dir,
        None, // No output directory needed for analysis
        num_threads,
        config,
        analyze_table_op
    )?;
    
    // Extract the Python dictionary from the result
    let result_dict = result_obj.downcast::<PyDict>(py)?;
    
    // Add detailed_results dictionary for table analysis
    let detailed_results = PyDict::new(py);
    result_dict.set_item("detailed_results", detailed_results)?;
    
    Ok(result_dict.into())
}

/// Python-exposed function for processing directory with original behavior
/// This maintains compatibility with existing Python code
#[pyfunction]
pub fn process_directory_native(
    py: Python,
    input_dir: &str,
    output_dir: &str,
    scripts_to_keep: Vec<String>,
    num_threads: usize,
) -> PyResult<PyObject> {
    // This is a wrapper around batch_clean_markdown_files for backward compatibility
    batch_clean_markdown_files(py, input_dir, output_dir, scripts_to_keep, num_threads)
}
