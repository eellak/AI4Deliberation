use pyo3::prelude::*;
use regex::Regex;
use lazy_static::lazy_static;

lazy_static! {
    // Regular expressions for table detection
    static ref TABLE_SEPARATOR_REGEX: Regex = Regex::new(r"^[\s]*\|[\s]*[-:]+[\s]*\|").unwrap();
    static ref TABLE_ROW_REGEX: Regex = Regex::new(r"^[\s]*\|.*\|[\s]*$").unwrap();
}

#[pyclass]
#[derive(Debug, Clone)]
pub struct TableIssue {
    #[pyo3(get, set)]
    pub line_number: usize,
    #[pyo3(get, set)]
    pub description: String,
    #[pyo3(get, set)]
    pub expected_columns: Option<usize>,
    #[pyo3(get, set)]
    pub found_columns: Option<usize>,
}

// New struct for richer return type from core logic
#[derive(Debug)]
pub struct TableScan {
    pub total_tables: usize,
    pub issues: Vec<Py<TableIssue>>,
}

#[allow(non_local_definitions)]
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

/// Core function to detect malformed tables in markdown text
// Updated to use the robust loop and return TableScan
pub fn core_detect_malformed_tables(py: Python, markdown_text: &str) -> PyResult<TableScan> {
    let mut issues: Vec<Py<TableIssue>> = Vec::new();
    let mut total_tables_count: usize = 0;
    let lines: Vec<&str> = markdown_text.lines().collect();
    
    let mut i = 0;
    while i < lines.len() {
        let line = lines[i];
        if TABLE_SEPARATOR_REGEX.is_match(line) {
            total_tables_count += 1;

            let header_row = if i > 0 && TABLE_ROW_REGEX.is_match(lines[i-1]) {
                Some(lines[i-1])
            } else {
                None
            };
            
            let separator_columns = count_table_columns(line);
            
            if let Some(header) = header_row {
                let header_columns = count_table_columns(header);
                if header_columns != separator_columns {
                    let issue = Py::new(py, TableIssue::new(
                        i + 1, // 1-based line number for separator line
                        "Table header and separator column count mismatch".to_string(),
                        Some(header_columns),
                        Some(separator_columns)
                    ))?;
                    issues.push(issue);
                }
            } else {
                let issue = Py::new(py, TableIssue::new(
                    i + 1, // 1-based line number for separator line
                    "Table separator without header row".to_string(),
                    None, // Expected columns might be unknown if no header
                    Some(separator_columns) // But we know the separator's columns
                ))?;
                issues.push(issue);
            }
            
            // Check table body rows for issues
            let mut current_row_idx = i + 1; // Start checking from line after separator
            while current_row_idx < lines.len() && TABLE_ROW_REGEX.is_match(lines[current_row_idx]) {
                let row_columns = count_table_columns(lines[current_row_idx]);
                // Only report issue if separator_columns is determined (e.g. > 0)
                if separator_columns > 0 && row_columns != separator_columns {
                    let issue = Py::new(py, TableIssue::new(
                        current_row_idx + 1, // 1-based line number for current row
                        "Table row has inconsistent column count".to_string(),
                        Some(separator_columns),
                        Some(row_columns)
                    ))?;
                    issues.push(issue);
                }
                current_row_idx += 1;
            }
            // Advance main index `i` past this table (separator and all rows just checked)
            // current_row_idx is now at the line *after* the last table row, or i + 1 if no body rows.
            i = current_row_idx -1; // minus 1 because outer loop increments i by 1 at the end
        }
        i += 1;
    }
    
    Ok(TableScan { total_tables: total_tables_count, issues })
}

/// Helper function to count columns in a table row
fn count_table_columns(row: &str) -> usize {
    let trimmed = row.trim();
    if trimmed.starts_with('|') && trimmed.ends_with('|') {
        if trimmed.len() == 1 { return 0; } // Handle degenerate case "|"
        let inner = &trimmed[1..trimmed.len()-1];
        return inner.matches('|').count() + 1;
    }
    0 // Not a valid table row structure for column counting this way
}

/// Python-exposed function for table analysis on a single string
// Converts TableScan to tuple for Python
#[pyfunction]
pub fn analyze_tables_in_string(py: Python, markdown_text: &str) -> PyResult<(usize, Vec<Py<TableIssue>>)> {
    let scan_result = core_detect_malformed_tables(py, markdown_text)?;
    Ok((scan_result.total_tables, scan_result.issues))
}

/// Process a single file for table analysis - intended for use by directory_processor
// Returns TableScan directly for internal Rust use.
pub fn analyze_table_file_op(py: Python, content: &str) -> PyResult<TableScan> {
    core_detect_malformed_tables(py, content)
}
