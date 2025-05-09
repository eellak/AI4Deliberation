use pyo3::prelude::*;
use pyo3::exceptions::PyValueError;
use pyo3::types::PyDict;
use rayon::prelude::*;
use rayon::ThreadPoolBuilder;
use std::collections::{HashMap, HashSet};
use std::fs::{self};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use walkdir::WalkDir;

use crate::cleaning_module;
use crate::table_analysis_module;

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
        .filter(|e| e.path().is_file() && e.path().extension().map_or(false, |ext| ext == "md"))
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
                                            drop(py_thread);
                                            
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
    let keys_to_include = ["punct", "num", "sym"]; // These match the keys in cleaning_module.rs
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
        
        // Use op_conf parameters consistently
        let cleaned_content = cleaning_module::core_clean_text(
            content, 
            &op_conf.allowed_chars, 
            &op_conf.unusual_chars
        );
        
        println!("DEBUG: Cleaned content has {} characters", cleaned_content.len());
        Ok(PerFileOperationOutput::Content(cleaned_content))
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
