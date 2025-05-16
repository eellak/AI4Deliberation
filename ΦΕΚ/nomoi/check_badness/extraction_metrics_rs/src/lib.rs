// Main module for the text_cleaner_rs Python module
// Implements refactored code with better separation of concerns

// Internal modules
mod cleaning_module;
mod table_analysis_module;
mod directory_processor;

// Export public items from modules via PyO3
use pyo3::prelude::*;

// Python module definition
#[pymodule]
fn text_cleaner_rs(_py: Python, m: &PyModule) -> PyResult<()> {
    // Functions from cleaning_module
    m.add_function(wrap_pyfunction!(cleaning_module::clean_text, m)?)?;
    m.add_function(wrap_pyfunction!(cleaning_module::analyze_text, m)?)?;
    m.add_function(wrap_pyfunction!(cleaning_module::list_available_scripts, m)?)?;
    
    // Functions from table_analysis_module
    m.add_class::<table_analysis_module::TableIssue>()?;
    m.add_function(wrap_pyfunction!(table_analysis_module::analyze_tables_in_string, m)?)?;
    
    // Functions from directory_processor
    // Add the new batch CSV generation function
    m.add_function(wrap_pyfunction!(directory_processor::batch_generate_table_summary_csv, m)?)?;

    // Kept other existing functions from directory_processor for now, assuming they serve other purposes.
    // If they are deprecated or replaced, they can be removed.
    m.add_function(wrap_pyfunction!(directory_processor::process_directory_native, m)?)?;
    m.add_function(wrap_pyfunction!(directory_processor::batch_clean_markdown_files, m)?)?;
    // The old batch_analyze_tables_in_files was commented out in previous step, which is good.
    m.add_function(wrap_pyfunction!(directory_processor::generate_analysis_report_for_directory, m)?)?;
    
    Ok(())
}
