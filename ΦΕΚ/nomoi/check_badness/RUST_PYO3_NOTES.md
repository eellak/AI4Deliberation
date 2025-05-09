# Notes on Rust and PyO3 Development for Text Cleaner

This document records best practices, challenges, and solutions encountered during the development of the Rust-based text cleaner with PyO3 bindings.

## General Observations

*   (To be filled as we progress)

## Specific Hurdles & Solutions

*   **Topic:** Dependency Management (`Cargo.toml`)
    *   **Challenge:** Ensuring all necessary crates are available before starting implementation of new features.
    *   **Solution:** Before modifying Rust code for new features (like directory processing or parallelism), always check `Cargo.toml` to confirm required crates (e.g., `walkdir`, `rayon`) are present and at suitable versions. In this case, both `walkdir` and `rayon` were already included, so no update was needed.

*   **Topic:** (e.g., Data Type Conversion, Lifetime Management, Error Handling)
    *   **Challenge:** (Description of the problem)
    *   **Solution:** (How it was addressed)

*   **Topic**: Internal vs. PyO3 Functions for Performance in Loops
    *   **Challenge**: Calling PyO3-wrapped functions (those marked with `#[pyfunction]`) repeatedly within a tight, performance-sensitive loop (e.g., inside Rayon's parallel iterators) can introduce unnecessary overhead. This overhead comes from the Foreign Function Interface (FFI) calls, Python object creation/conversion, and GIL management that PyO3 handles.
    *   **Solution**: For core logic that needs to be executed many times rapidly (like processing individual files in a batch), extract this logic into private/internal Rust functions. These internal functions should operate purely on native Rust types. The `#[pyfunction]` can then orchestrate calls to these internal helpers. This minimizes FFI overhead within the hot path of the parallel processing, leading to better performance.

## PyO3 Best Practices Noted

*   (To be filled)

# Troubleshooting PyO3 Rust Extension Import Issues

This document outlines the debugging process and findings related to an issue where a Python script using a Rust PyO3 extension (`text_cleaner_rs`) was stalling unexpectedly.

## 1. The Problem

A Python script (`ΦΕΚ/nomoi/check_badness/clean_markdown_files.py`) designed to call Rust functions for cleaning Markdown files (from `ΦΕΚ/nomoi/check_badness/extraction_metrics_rs/`) was consistently stalling.
Log output showed messages like:
```
INFO: Using 4 threads for processing 2 files
INFO: Starting parallel processing of 2 files
INFO: Using chunk size of 10 for 4 threads
INFO: Reading all files into memory...
INFO: Read 2 files into memory, starting processing
```
These messages were *not* present in the current Rust source code (`cleaning_module.rs`, `directory_processor.rs`) nor in the Python calling script (`clean_markdown_files.py`). The script would hang indefinitely after the "Read 2 files into memory, starting processing" message.

## 2. Investigation Steps

The investigation involved several steps:

1.  **Verifying Log Origins**:
    *   Searched the Rust project source files for the unexpected log messages. None were found.
    *   Searched the main Python calling script (`clean_markdown_files.py`) for these messages. None were found.
    *   This indicated that the logs were originating from a piece of code not immediately visible in the main project files being edited.

2.  **Examining the Python Environment (`/mnt/data/venv/`)**:
    *   Listed the contents of the virtual environment's `site-packages` directory (`/mnt/data/venv/lib/python3.10/site-packages/`).
    *   Initially, a `text_cleaner_rs/` directory (Python package structure) was found alongside `text_cleaner_rs.so` and `text_cleaner_rs-*.dist-info`.
    *   Cleanup steps were performed to remove the Python package structure and dist-info from the venv, leaving only the `text_cleaner_rs.so` file, aiming for a direct import of the compiled Rust extension.
    *   Despite these cleanups within the venv, the unexpected log messages and stalling persisted.

3.  **Identifying the Actual Imported Module**:
    *   The crucial step was to determine exactly which file Python was importing when `import text_cleaner_rs` was executed.
    *   The command `python3 -c "import text_cleaner_rs; print(text_cleaner_rs.__file__)"` was run.
    *   **Key Finding**: This command revealed that Python was importing from `/home/glossapi/.local/lib/python3.10/site-packages/text_cleaner_rs/__init__.py`.

4.  **Checking `sys.path`**:
    *   The command `source /mnt/data/venv/bin/activate && python3 -c "import sys; print(sys.path)"` was run to inspect Python's module search path when the virtual environment was active.
    *   This confirmed that the venv's `site-packages` directory was in `sys.path`.

## 3. Root Cause

The root cause was a **user-level Python package installation shadowing the virtual environment's package**.

*   An older or different version of the `text_cleaner_rs` package was installed in the user's local site-packages directory (`/home/glossapi/.local/lib/python3.10/site-packages/`).
*   This user-level installation contained Python wrapper code (likely an `__init__.py` and other Python files) that included the logic for printing "Reading all files into memory..." and was likely responsible for the stalling behavior.
*   Python's import mechanism was resolving `import text_cleaner_rs` to this user-level package *before* considering the one in the activated virtual environment, possibly due to the order of paths in `sys.path` or how user-site packages are prioritized by the system's Python configuration.

## 4. The Solution

The solution involved ensuring that the Python interpreter used the intended compiled Rust extension from the project's virtual environment:

1.  **Removing the User-Level Package**:
    *   The user-level `text_cleaner_rs` package was uninstalled/removed:
        ```bash
        # Attempted pip uninstall (might not work if not pip-installed)
        # python3 -m pip uninstall text_cleaner_rs -y
        # Manual removal as fallback
        rm -rf /home/glossapi/.local/lib/python3.10/site-packages/text_cleaner_rs
        rm -rf /home/glossapi/.local/lib/python3.10/site-packages/text_cleaner_rs-*.dist-info
        ```

2.  **Verifying Correct Import Path**:
    *   After activating the virtual environment (`source /mnt/data/venv/bin/activate`), the import path was re-verified:
        ```bash
        python3 -c "import text_cleaner_rs; print(text_cleaner_rs.__file__)"
        ```
    *   This correctly showed `/mnt/data/venv/lib/python3.10/site-packages/text_cleaner_rs.so`, indicating the direct compiled extension was now being imported.

3.  **Re-running the Script**:
    *   The main Python script (`clean_markdown_files.py`) was run again.
    *   The extraneous log messages disappeared, and the script executed correctly (calling the simplified Rust debug logic at that stage).

## 5. Key Takeaways and Future Prevention

*   **Python's Import Precedence**: Be aware of Python's `sys.path` and how it resolves imports. User-level site-packages can override or "shadow" packages in virtual environments if not carefully managed or if the `PYTHONPATH` or system configuration gives them precedence.
*   **Verify with `module.__file__`**: When encountering unexpected module behavior or suspecting the wrong version of a module is being used, always check `module.__file__` to see the exact path of the imported module.
*   **Check `sys.path`**: Use `import sys; print(sys.path)` to understand the search order Python is using.
*   **Isolate Environments**: Virtual environments are designed to prevent such conflicts. Ensure they are correctly activated and that there are no overriding user-level or global installations for project-specific dependencies unless explicitly intended.
*   **Clean Installations**: When troubleshooting, ensure a clean state by removing potentially conflicting versions of packages from all possible locations (global, user, venv), then reinstalling only where needed (typically within the venv).
*   **PyO3 Build/Installation**: When building and installing PyO3 extensions, be mindful of where the final package or `.so` file is placed and how it's intended to be imported. Tools like `maturin develop` vs `maturin build --release` followed by `pip install` can have different outcomes for where packages are installed.

This detailed documentation should help in quickly diagnosing similar import-related issues in the future.
