## TODO list for Refactoring Rust + PyO3 Cleaning Pipeline

### 0 · Preparation

*   **Actioned:** Ensure `criterion` and `cargo-flamegraph` are considered for benchmarking (user responsibility).
*   **Actioned:** Added dependencies to `Cargo.toml`:
    ```toml
    memchr       = "2"
    aho-corasick = "1"
    he           = "1"
    ```

---

### 1 · Logic fixes (high priority)

| Step    | What                                     | How                                                                                                                                                                                                                                                                                                                | Status      |
| ------- | ---------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------- |
| **1.1** | **Count Greek & Latin *after* cleaning** | In `perform_text_analysis`: 1) run `core_clean_text` first 2) iterate **cleaned\\_text** to compute `greek_after`, `latin_after`, `non_ws_after`. 3) Extend `SlimTextAnalysisResult`:<br>`greek_char_count_after_clean: usize`, `latin_char_count_after_clean: usize`, `cleaned_non_whitespace_chars_after_clean: usize`. 4) When writing CSV use those fields. | Done        |
| **1.2** | **Tighten glyph detection**              | Replace `GLYPH_WORD_REGEX` (`\\S*glyph\\S*`) with **substring test**: `"glyph<c="` or `"glyph&lt;c="`. Implement with the upcoming Aho-Corasick matcher (see 2.1).                                                                                                                                                   | Done        |
| **1.3** | **Handle closed / malformed tags**       | Stream-strip will ignore any `<…>`; no open/close validation needed once we switch (see 5.1).                                                                                                                                                                                                                      | Pending (on 5.1) |

---

### 2 · Line-level removal

| Step    | What                         | How                                                                                                                                                                                              | Status  |
| ------- | ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------- |
| **2.1** | **Define artefact triggers** | At top of `cleaning_module.rs`:<br>`static BAD_LINE_AC: AhoCorasick = AhoCorasick::new([<br>    "glyph<c=", "glyph&lt;c=", "MS-Bold-", "font=/", "FontName="]);`                     | Done    |
| **2.2** | **Early-reject such lines**  | First line in `core_clean_text` loop:<br>`if BAD_LINE_AC.is_match(line) {<br>    cleaned_output.push_str(TEXT_MISSING_COMMENT);<br>    cleaned_output.push(\'\\n\');<br>    continue;<br>}` | Done    |
| **2.3** | **Side-effect**              | Because the whole line is gone, per-char removal count (for the comment threshold) becomes moot — keep `TEXT_MISSING_COMMENT` unconditionally here.                                              | Done    |

---

### 3 · Badness score simplification

| Step    | What                      | How                                                                                                                                                                                                                            | Status  |
| ------- | ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------- |
| **3.1** | **Count during cleaning** | While scanning each char in the main loop, `kept += 1`, `original += 1`. At the end of the file:<br>`badness = 1.0 - kept as f64 / original as f64`.<br>*(No second pass, no whitespace filtering needed unless you want it.)* | Done    |
| **3.2** | **Expose both variants**  | If non-whitespace ratio is still useful, return both `badness_all_chars` and `badness_non_ws` in `SlimTextAnalysisResult`; CSV can pick the one you prefer.                                                                    | Done    |

---

### 4 · Corner-case handling

| Step    | What                              | How                                                                                                                                                                           | Status  |
| ------- | --------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- |
| **4.1** | **Strip HTML entities or decode** | Add after tag removal:<br>`let line = he::decode_html_entities(no_tags);` <br>*(Crate `he = "1"`)*<br>OR drop them with Aho-Corasick (`"&lt;"`, `"&gt;"`, `"&amp;"`, `"&#"`). | Done    |
| **4.2** | **Treat comment-only lines**      | If a line becomes exactly `<!-- … -->` after cleaning, treat it as blank (no extra comment). Regex for HTML comments is fine & not hot.                                       | Done    |
| **4.3** | **Expose `min_comment_chars`**    | In `clean_text` signature add `min_comment_chars: Option<usize>`; default to previous `5`.                                                                                    | Done    |

---

### 5 · Performance upgrades (after correctness)

| Step    | What                                          | How                                                                                                                                       | Est. gain\* | Status  |
| ------- | --------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- | ----------- | ------- |
| **5.1** | **Replace regex `<[^>]*>` with stream-strip** | Implement helper:<br>`strip_tags(line: &str) -> (Cow<\'_, str>, usize)` using `memchr` loop.                                                | \~ 2 - 3 ×  | Done    |
| **5.2** | **Remove `GLYPH_WORD_REGEX`**                 | Already handled by **BAD\\_LINE\\_AC**; delete the regex constant.                                                                          | small       | Done    |
| **5.3** | **Drop HashSet for ASCII/Late-BMP**           | Build a `static [bool; 1024]` bit-table of \"allowed\"; `if c as u32 <= 0x3FF && ALLOWED_BITMAP[c as usize]` is faster than `HashSet::contains`. | 15-25 %     | Done    |
| **5.4** | **Reuse buffers**                             | Allocate one `String`/`Vec` per file, clear & reuse per line to avoid allocator churn.                                                    | small       | Done    |
| **5.5** | **Profile again**                             | Run `cargo bench` and `flamegraph` to ensure regex is no longer dominant.                                                                 | —           | Pending (User) |

---

### 6 · Update tests & Python bindings

1.  Extend unit tests in `tests/cleaning.rs` to assert:
    *   Greek % + Latin % ≈ will  not equal 100 % since the text will have number, punctuation and other missed "dirty" elements.
    *   `