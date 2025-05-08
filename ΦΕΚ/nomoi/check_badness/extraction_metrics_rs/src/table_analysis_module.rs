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
pub fn core_detect_malformed_tables(py: Python, markdown_text: &str) -> PyResult<Vec<Py<TableIssue>>> {
    let mut issues: Vec<Py<TableIssue>> = Vec::new();
    let lines: Vec<&str> = markdown_text.lines().collect();
    
    // Find all table separator lines (potential table headers)
    for (i, line) in lines.iter().enumerate() {
        if TABLE_SEPARATOR_REGEX.is_match(line) {
            // Found a table separator line, check surrounding lines
            
            // Check if previous line exists and is a header row
            let header_row = if i > 0 && TABLE_ROW_REGEX.is_match(lines[i-1]) {
                Some(lines[i-1])
            } else {
                None
            };
            
            // Count columns in separator
            let separator_columns = count_table_columns(line);
            
            // Check header columns if header exists
            if let Some(header) = header_row {
                let header_columns = count_table_columns(header);
                
                // Column count mismatch issue
                if header_columns != separator_columns {
                    let issue = Py::new(py, TableIssue::new(
                        i + 1, // 1-based line number
                        "Table header and separator column count mismatch".to_string(),
                        Some(header_columns),
                        Some(separator_columns)
                    ))?;
                    issues.push(issue);
                }
            } else {
                // No header row found
                let issue = Py::new(py, TableIssue::new(
                    i + 1,
                    "Table separator without header row".to_string(),
                    None,
                    None
                ))?;
                issues.push(issue);
            }
            
            // Check table body rows if they exist
            let mut row_index = i + 1;
            while row_index < lines.len() && TABLE_ROW_REGEX.is_match(lines[row_index]) {
                let row_columns = count_table_columns(lines[row_index]);
                
                // Column count mismatch with separator
                if row_columns != separator_columns {
                    let issue = Py::new(py, TableIssue::new(
                        row_index + 1,
                        "Table row has inconsistent column count".to_string(),
                        Some(separator_columns),
                        Some(row_columns)
                    ))?;
                    issues.push(issue);
                }
                
                row_index += 1;
            }
        }
    }
    
    Ok(issues)
}

/// Helper function to count columns in a table row
fn count_table_columns(row: &str) -> usize {
    // Remove outer pipes and count remaining pipes + 1
    let trimmed = row.trim();
    if trimmed.starts_with('|') && trimmed.ends_with('|') {
        let inner = &trimmed[1..trimmed.len()-1];
        return inner.matches('|').count() + 1;
    }
    0 // Not a valid table row
}

/// Python-exposed function for table analysis on a single string
#[pyfunction]
pub fn analyze_tables_in_string(py: Python, markdown_text: &str) -> PyResult<Vec<Py<TableIssue>>> {
    core_detect_malformed_tables(py, markdown_text)
}

/// Process a single file for table analysis - simplified to avoid lifetime issues
pub fn analyze_table_file_op(py: Python, content: &str) -> PyResult<Vec<Py<TableIssue>>> {
    // Run table analysis directly
    core_detect_malformed_tables(py, content)
}
