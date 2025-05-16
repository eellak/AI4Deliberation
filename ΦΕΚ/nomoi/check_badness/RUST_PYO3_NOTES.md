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

## Additional PyO3 Troubleshooting & Build Notes (Post-Initial Setup)

*   **Topic:** Missing Crates for `Lazy` Statics (e.g., `once_cell`)
    *   **Challenge:** When using `once_cell::sync::Lazy` (or similar constructs for one-time initialization of static variables, often with `Regex`), the build can fail if the `once_cell` crate is not added to `Cargo.toml`.
    *   **Error Example:** `error[E0433]: failed to resolve: use of unresolved module or unlinked crate \`once_cell\``
    *   **Solution:** Add the required crate to the `[dependencies]` section of your `Cargo.toml` file. For example: `once_cell = \"1.19.0\"` (or the latest compatible version).

*   **Topic:** Ensuring Python Loads the *Latest* Compiled Rust Extension
    *   **Challenge:** After making changes to Rust code and rebuilding with `maturin develop` (or similar), Python might still load an older, cached version of the extension from `site-packages`, leading to errors like "function takes X arguments but Y were given" or other unexpected behavior reflecting old code.
    *   **Diagnosis Steps:**
        1.  Activate your virtual environment: `source /path/to/your/venv/bin/activate`
        2.  Run a Python command to check the loaded module's file path: 
            `/path/to/your/venv/bin/python -c "import your_rust_module_name; print(your_rust_module_name.__file__)"`
            (Replace `your_rust_module_name` with the actual name, e.g., `text_cleaner_rs`).
        3.  Inspect the output. If it points to an `.so` file (or similar, like a `__init__.py` in a directory for older `maturin` versions) within your project's `target` directory or a temporary build directory, `maturin develop` might be working as intended by linking directly. However, if it points to a stale copy in `site-packages` that doesn't reflect recent changes, you have a caching issue.
    *   **Solution (Force Update in Virtual Environment):**
        1.  **Clean Old Versions from `site-packages` (within the active venv):**
            *   Identify the paths. Common locations in a venv (`<venv_path>/lib/pythonX.Y/site-packages/`) include:
                *   `your_rust_module_name.so`
                *   `your_rust_module_name/` (directory, for some older package structures)
                *   `your_rust_module_name-*.dist-info/` (directory)
            *   Remove them (be careful with `rm -rf`):
                ```bash
                VENV_SITE_PACKAGES=/path/to/your/venv/lib/pythonX.Y/site-packages
                rm -rf $VENV_SITE_PACKAGES/your_rust_module_name.so
                rm -rf $VENV_SITE_PACKAGES/your_rust_module_name
                rm -rf $VENV_SITE_PACKAGES/your_rust_module_name-*.dist-info
                ```
        2.  **Rebuild and Install with `maturin develop`:**
            *   Navigate to your Rust project directory (where `Cargo.toml` is).
            *   Ensure your virtual environment is still active.
            *   Run: `maturin develop` (or `source /path/to/venv/bin/activate && maturin develop` if you need to ensure activation in the same command context for the tool).
        3.  **Re-verify:** Repeat the diagnosis step to confirm Python now loads the extension from the correct, updated path (often a link managed by `maturin develop` or a newly copied `.so` file in `site-packages`).
    *   **Context:** This issue was specifically encountered when a function signature in Rust (`analyze_text`) was changed (added a parameter), but Python kept calling the old signature because `maturin develop` hadn't correctly updated or Python hadn't picked up the fresh build from `site-packages` until the old versions were manually cleared.
