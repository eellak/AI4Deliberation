# TODO for Rust Table Analysis Module

- [ ] Modify `table_analysis_module.rs` (`core_detect_malformed_tables` and its PyO3 wrapper `analyze_tables_in_string`):
    - The function should detect all occurrences of table structures (e.g., based on Markdown table separator lines `|---|`).
    - It should return a count of *total tables detected* in addition to the current list of `TableIssue` objects for malformed tables.
    - The preferred return type from `analyze_tables_in_string` would be a tuple: `(total_tables_detected: usize, issues: Vec<Py<TableIssue>>)`.

- [ ] Update `directory_processor.rs` (`batch_analyze_tables_in_files`):
    - This function should call the modified `analyze_tables_in_string`.
    - It needs to correctly process the tuple `(total_tables_detected, issues_list)` for each file.
    - It should aggregate these results to be returned to Python, likely in a dictionary where keys are file paths and values contain counts for total tables, badly formed tables (length of `issues_list`), and well-formed tables (total - badly_formed).

- [ ] Update `table_detector.py`:
    - Modify it to call `batch_analyze_tables_in_files`.
    - Process the detailed dictionary returned by the Rust function.
    - Generate a CSV report with one row per file, and columns: `file`, `total_tables`, `badly_formed_tables`, `well_formed_tables`. 