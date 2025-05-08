# Proposal for Refactoring Table Analysis in `extraction_metrics_rs`

**Date:** 2025-05-08

## 1. Introduction and Goals

This document outlines a proposal to refactor the Markdown table analysis capabilities within the `extraction_metrics_rs` Rust crate. The primary goals are:

*   **Comprehensive Table Detection:** Reliably identify all GFM-style Markdown tables in input files.
*   **Accurate Well-Formedness Classification:** Classify each detected table as either "well-formed" or "malformed" based on defined criteria.
*   **Detailed Reporting:** Provide structured information for each file, including total table counts, counts of well-formed and malformed tables, and details for each table (location, dimensions, specific issues).
*   **Rust-Centric Processing:** Shift the primary responsibility for file iteration, concurrency, and analysis logic to Rust, making Python scripts (like `table_detector_enhanced.py`) thin wrappers.
*   **Efficiency:** Implement an efficient processing pipeline, leveraging parallelism and optimized string operations.

## 2. Core Requirements & Design Philosophy

*   The Rust crate will expose a single primary function (e.g., `batch_analyze_markdown_tables`) that takes an input directory path and returns a collection of analysis results, one for each processed Markdown file.
*   Concurrency (parallel processing of files) will be handled internally by Rust using `rayon`.
*   Error handling for file I/O and parsing will be managed within Rust, with clear error reporting.
*   Python will be used for invoking the Rust batch function and potentially for user-facing interactions or further data manipulation on the results returned by Rust.

## 3. Proposed Data Structures (Rust - exposed via PyO3)

These structures will be defined in `table_analysis_module.rs` and exposed to Python.

```rust
use pyo3::prelude::*;

// Existing structure - review if any additions are needed
#[pyclass(get_all, set_all)]
#[derive(Debug, Clone)]
pub struct TableIssue {
    pub line_number: usize,         // 1-based line number where the issue occurs
    pub description: String,        // Description of the issue
    pub expected_columns: Option<usize>,
    pub found_columns: Option<usize>,
}

#[pymethods]
impl TableIssue {
    #[new]
    pub fn new(line_number: usize, description: String, expected_columns: Option<usize>, found_columns: Option<usize>) -> Self {
        TableIssue { line_number, description, expected_columns, found_columns }
    }
    // __repr__ etc.
}

#[pyclass(get_all, set_all)]
#[derive(Debug, Clone)]
pub struct TableInfo {
    pub start_line: usize,          // 1-based line number where the table starts (header row)
    pub end_line: usize,            // 1-based line number where the table ends
    pub rows: usize,                // Number of data rows (excluding header and separator)
    pub columns: usize,             // Number of columns detected (from separator line)
    pub is_well_formed: bool,
    pub issues: Vec<Py<TableIssue>>, // List of specific issues if malformed
}

#[pymethods]
impl TableInfo {
    #[new]
    pub fn new(start_line: usize, end_line: usize, rows: usize, columns: usize, is_well_formed: bool, issues: Vec<Py<TableIssue>>) -> Self {
        TableInfo { start_line, end_line, rows, columns, is_well_formed, issues }
    }
    // __repr__ etc.
}

#[pyclass(get_all, set_all)]
#[derive(Debug, Clone)]
pub struct FileTableAnalysisResult {
    pub file_path: String,             // Relative path of the analyzed file
    pub total_tables: usize,
    pub well_formed_tables: usize,
    pub badly_formed_tables: usize,
    pub tables_info: Vec<Py<TableInfo>>, // Detailed info for each table
    pub error_message: Option<String>,   // For file-level errors (e.g., read error)
}

#[pymethods]
impl FileTableAnalysisResult {
    #[new]
    pub fn new(file_path: String, total_tables: usize, well_formed_tables: usize, badly_formed_tables: usize, tables_info: Vec<Py<TableInfo>>, error_message: Option<String>) -> Self {
        FileTableAnalysisResult {
            file_path,
            total_tables,
            well_formed_tables,
            badly_formed_tables,
            tables_info,
            error_message,
        }
    }
    // __repr__ etc.
}
```

## 4. Markdown Table Standards and Parsing Strategy

*   **Standard:** We will target GitHub Flavored Markdown (GFM) tables.
    *   A table is an arrangement of data with rows and columns, consisting of a single header row, a delimiter row separating the header from the content, and zero or more data rows.
    *   Format: `| Head1 | Head2 |\n|---|---|\n| Cell1 | Cell2 |`
*   **Detection Algorithm (`core_analyze_all_tables` in `table_analysis_module.rs`):
    1.  Iterate through lines of the file content.
    2.  **Table Start Heuristic:** Look for a potential separator line (`TABLE_SEPARATOR_REGEX: ^\s*\|\s*[-:]+\s*\|`).
    3.  If a separator line is found:
        *   Check the **preceding line**. It **must** be a valid table row (`TABLE_ROW_REGEX: ^\s*\|.*\|\s*$`) to be considered the header.
        *   If no valid header is found immediately preceding the separator, this is **not considered a GFM table start** for our counting purposes, but could be flagged as a structural anomaly if desired (though the primary goal is to count well-formed/malformed tables).
    4.  If a header and separator are found, this marks the beginning of a table (`TableInfo.start_line = header_line_number`).
    5.  Determine `TableInfo.columns` from the separator line (count `|` occurrences between the outer pipes + 1).
    6.  Consume subsequent lines as data rows as long as they match `TABLE_ROW_REGEX`.
    7.  The table ends when a line does not match `TABLE_ROW_REGEX` or EOF is reached (`TableInfo.end_line = last_data_row_line_number`).
    8.  During this process, apply well-formedness checks (see next section).

## 5. Criteria for Well-Formed vs. Malformed Tables

A table is **well-formed** if all the following conditions are met:

1.  **Header Presence:** A valid header row (matching `TABLE_ROW_REGEX`) exists immediately before the separator row.
2.  **Separator Validity:** The separator row matches `TABLE_SEPARATOR_REGEX`.
3.  **Column Count Consistency:**
    *   The number of columns in the header row must equal the number of columns defined by the separator row.
    *   Each data row must have a number of columns equal to that defined by the separator row.

Any deviation results in the table being classified as **malformed**, and specific `TableIssue`s will be recorded:

*   `TableIssue`: "Table separator without header row" (Line: separator line number).
*   `TableIssue`: "Table header and separator column count mismatch" (Line: separator line number, Expected: header_cols, Found: separator_cols).
*   `TableIssue`: "Table row has inconsistent column count" (Line: data row line number, Expected: separator_cols, Found: row_cols).

## 6. Efficiency and Accuracy Considerations

*   **Parallelism:** `directory_processor.rs` will use `rayon::scope` or `par_iter` to process multiple files in parallel. File reading and string processing for table analysis will occur in these parallel tasks.
*   **Regex Efficiency:** Current regexes are simple. `lazy_static!` ensures they are compiled once. Avoid overly complex regexes in tight loops.
*   **String Operations:** Iterate over lines (`.lines()`) to avoid large string copies. Work with string slices (`&str`) as much as possible.
*   **Heuristics for Table Detection:** The `TABLE_SEPARATOR_REGEX` is a strong positive indicator. Checking the line above for a `TABLE_ROW_REGEX` match is a quick and effective way to confirm a likely table header.
*   **Accuracy:** The proposed algorithm focuses on GFM tables. It will not attempt to parse more complex or non-standard table-like structures. The primary goal is robust detection of standard Markdown tables.
*   **File I/O:** Use buffered readers (`std::io::BufReader`) for efficient file reading.

## 7. Proposed Changes to `table_analysis_module.rs`

1.  **Add `TableInfo` and `FileTableAnalysisResult` structs** as `#[pyclass]` (defined in section 3).
2.  **Create `core_analyze_all_tables(py: Python, markdown_text: &str, file_path_for_logging: &str) -> PyResult<Py<FileTableAnalysisResult>>`:**
    *   Implement the table detection and classification logic described in sections 4 & 5.
    *   Iterate through lines, identify table blocks (header, separator, data rows).
    *   For each block, validate it and create a `TableInfo` object.
    *   Collect all `TableIssue`s for malformed tables within their respective `TableInfo`.
    *   Aggregate results into `FileTableAnalysisResult`, calculating total, well-formed, and malformed counts.
3.  **Modify/Create `#[pyfunction] analyze_markdown_string_for_tables(py: Python, markdown_text: &str) -> PyResult<Py<FileTableAnalysisResult>>`:**
    *   This function will call `core_analyze_all_tables`.
    *   It serves as the primary entry point for analyzing a single string of Markdown content.

## 8. Proposed Changes to `directory_processor.rs`

1.  **Add `#[pyfunction] batch_analyze_markdown_tables(py: Python, input_dir: String, num_threads: usize) -> PyResult<Vec<Py<FileTableAnalysisResult>>>`:**
    *   Takes an input directory path and the number of threads (0 for auto, similar to `batch_clean_markdown_files`).
    *   Uses `walkdir` or `std::fs::read_dir` (recursively) to find all `.md` files.
    *   Uses `rayon` to parallelize the processing of these files:
        *   For each file path:
            *   Read file content.
            *   Call `table_analysis_module::core_analyze_all_tables` (or a wrapper around it that handles PyO3 context per thread if necessary).
            *   Collect the `FileTableAnalysisResult`.
            *   Handle file read errors by creating a `FileTableAnalysisResult` with an `error_message` and zero counts.
    *   Returns a `Vec<Py<FileTableAnalysisResult>>` to Python.

## 9. Proposed Changes to `lib.rs`

1.  **Add the new `PyClass`es to the module:**
    ```rust
    m.add_class::<table_analysis_module::TableInfo>()?;
    m.add_class::<table_analysis_module::FileTableAnalysisResult>()?;
    // TableIssue is already there
    ```
2.  **Remove or deprecate old table analysis functions if they are superseded.**
3.  **Add the new batch processing function:**
    ```rust
    m.add_function(wrap_pyfunction!(directory_processor::batch_analyze_markdown_tables, m)?)?;
    ```
4.  **Keep `analyze_tables_in_string` (or its new version `analyze_markdown_string_for_tables`)** from `table_analysis_module` if direct string analysis is still desired from Python, but ensure it returns the new `FileTableAnalysisResult`.

## 10. Python Wrapper (`table_detector_enhanced.py` or similar)

The Python script would be simplified:

1.  Import `text_cleaner_rs`.
2.  Call `text_cleaner_rs.batch_analyze_markdown_tables(input_dir, threads)`.
3.  Receive a list of `FileTableAnalysisResult` objects.
4.  Iterate through these results to generate CSV reports or other desired outputs.
    *   All complex logic (file walking, table parsing, concurrency) is now handled by Rust.

## 11. Conclusion

This refactoring will lead to a more robust, efficient, and maintainable table analysis system. By centralizing the core logic in Rust and leveraging its performance and concurrency features, we can achieve significant improvements in processing speed and simplify the Python integration layer. The clear data structures will provide comprehensive insights into table quality across large datasets of Markdown files.
