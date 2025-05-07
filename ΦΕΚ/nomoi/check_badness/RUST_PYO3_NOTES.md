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
