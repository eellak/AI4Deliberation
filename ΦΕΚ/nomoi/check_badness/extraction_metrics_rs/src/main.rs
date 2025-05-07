use csv::Writer;
use lazy_static::lazy_static;
use rayon::prelude::*;
use regex::Regex;
use serde::Serialize;
use std::collections::HashSet;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::Instant;
use walkdir::WalkDir;

// Regular expressions for detection (compiled once)
lazy_static! {
    // Modified to only count tags at word boundaries or line start/end
    static ref GLYPH_TAG_REGEX_RAW: Regex = Regex::new(r"(?:^|\s)glyph<c=\d+,font=/[^>]+>(?:\s|$)").unwrap();
    static ref GLYPH_TAG_REGEX_HTML: Regex = Regex::new(r"(?:^|\s)glyph&lt;c=\d+,font=/[^>]+&gt;(?:\s|$)").unwrap();
    static ref ANY_TAG_REGEX: Regex = Regex::new(r"(?:^|\s)<[^>]*>(?:\s|$)").unwrap();
    static ref IS_COMMENT_REGEX: Regex = Regex::new(r"^<!--").unwrap();
    static ref HTML_ENTITY_REGEX: Regex = Regex::new(r"&[a-zA-Z]+;|&#\d+;|&lt;|&gt;|&amp;").unwrap();
    
    // Regex for cleaning - detect any word containing "glyph"
    static ref GLYPH_WORD_REGEX: Regex = Regex::new(r"\S*glyph\S*").unwrap();
    
    // Regex for HTML comments
    static ref COMMENT_REGEX: Regex = Regex::new(r"<!--.*?-->").unwrap();
    
    // Regex for HTML/XML tags
    static ref ANY_TAG_CLEANING_REGEX: Regex = Regex::new(r"<[^>]*>").unwrap();
}

// Character sets for efficient checking
lazy_static! {
    static ref GREEK_CHARS: HashSet<char> = {
        let mut chars = HashSet::new();
        
        // Basic Greek Unicode block (0x0370-0x03FF)
        for code in 0x0370..0x0400 {
            if let Some(c) = std::char::from_u32(code) {
                chars.insert(c);
            }
        }
        
        // Add additional accented Greek (tonos, dialytika, etc.)
        let accented_greek = "άέήίόύώΆΈΉΊΌΎΏϊϋΪΫΐΰ";
        for c in accented_greek.chars() {
            chars.insert(c);
        }
        
        chars
    };
    
    static ref LATIN_CHARS: HashSet<char> = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ".chars().collect();
    
    // Common Spanish and French accented characters to exclude from unusual list
    static ref COMMON_ACCENTED_CHARS: HashSet<char> = {
        let mut chars = HashSet::new();
        // Spanish accented vowels
        for c in "áéíóúüñÁÉÍÓÚÜÑ¿¡".chars() {
            chars.insert(c);
        }
        // French accented vowels
        for c in "àèìòùâêîôûëïüÿçÀÈÌÒÙÂÊÎÔÛËÏÜŸÇ«»".chars() {
            chars.insert(c);
        }
        // Common European symbols
        for c in "€£¥©®™°§".chars() {
            chars.insert(c);
        }
        chars
    };
    
    // Set of unusual characters for checking and cleaning
    static ref UNUSUAL_CHARS: HashSet<char> = {
        let mut chars = HashSet::new();
        
        // Latin-1 Supplement (0x0080-0x00FF)
        for code in 0x0080..0x0100 {
            if let Some(c) = std::char::from_u32(code) {
                if !COMMON_ACCENTED_CHARS.contains(&c) { // Skip common accented chars
                    chars.insert(c);
                }
            }
        }
        
        // Latin Extended-A (0x0100-0x017F)
        for code in 0x0100..0x0180 {
            if let Some(c) = std::char::from_u32(code) {
                if !COMMON_ACCENTED_CHARS.contains(&c) { // Skip common accented chars
                    chars.insert(c);
                }
            }
        }
        
        // Latin Extended-B (0x0180-0x024F)
        for code in 0x0180..0x0250 {
            if let Some(c) = std::char::from_u32(code) {
                chars.insert(c);
            }
        }
        
        // IPA Extensions (0x0250-0x02AF)
        for code in 0x0250..0x02B0 {
            if let Some(c) = std::char::from_u32(code) {
                chars.insert(c);
            }
        }
        
        // Latin Extended Additional (0x1E00-0x1EFF)
        for code in 0x1E00..0x1F00 {
            if let Some(c) = std::char::from_u32(code) {
                chars.insert(c);
            }
        }
        
        chars
    };
}

#[derive(Debug, Serialize)]
struct FileMetrics {
    filename: String,
    base_name: String,
    glyph_count: usize,   // Combined total glyph count
    tag_count: usize,     // Combined tag count (HTML entities + XML tags)
    unusual_chars_count: usize, // Count of unusual characters
    greek_percentage: i32, // Rounded to nearest 1%
    latin_percentage: i32, // Rounded to nearest 1%
}

#[derive(Debug, Serialize)]
struct CleaningStats {
    filename: String,
    comment_count: usize,
    max_consecutive_comments: usize,
}

fn analyze_file(file_path: &Path) -> Result<FileMetrics, String> {
    // Get file metadata
    let filename = file_path.file_name()
        .and_then(|name| name.to_str())
        .ok_or_else(|| format!("Invalid filename: {:?}", file_path))?
        .to_string();
    
    let base_name = file_path.file_stem()
        .and_then(|name| name.to_str())
        .ok_or_else(|| format!("Invalid filename: {:?}", file_path))?
        .to_string();
    
    // Read file content
    let content = fs::read_to_string(file_path)
        .map_err(|e| format!("Failed to read file: {}", e))?;
    
    // Count total non-whitespace characters for percentage calculations
    let total_chars = content.chars().filter(|c| !c.is_whitespace()).count();
    
    // Count glyph tags using regex
    let raw_glyph_count = GLYPH_TAG_REGEX_RAW.find_iter(&content).count();
    let html_glyph_count = GLYPH_TAG_REGEX_HTML.find_iter(&content).count();
    let glyph_count = raw_glyph_count + html_glyph_count;
    
    // Count HTML entities
    let html_entity_count = HTML_ENTITY_REGEX.find_iter(&content).count();
    
    // Count XML tags (excluding comments)
    let xml_tag_count = ANY_TAG_REGEX.find_iter(&content)
        .filter(|tag_match| {
            let tag = &content[tag_match.start()..tag_match.end()];
            !IS_COMMENT_REGEX.is_match(tag)
        })
        .count();
    
    // Combined tag count
    let tag_count = html_entity_count + xml_tag_count;
    
    // Count unusual characters - using all originally specified Unicode blocks
    let unusual_chars_count = content.chars()
        .filter(|&c| UNUSUAL_CHARS.contains(&c))
        .count();
    
    // Calculate percentage of Greek and Latin alphabet characters
    let greek_count = content.chars()
        .filter(|c| GREEK_CHARS.contains(c))
        .count();
    
    let latin_count = content.chars()
        .filter(|c| LATIN_CHARS.contains(c))
        .count();
    
    // Calculate percentages and round to nearest 1%
    let greek_percentage = if total_chars > 0 { 
        ((greek_count as f64 / total_chars as f64) * 100.0).round() as i32 
    } else { 
        0 
    };
    
    let latin_percentage = if total_chars > 0 { 
        ((latin_count as f64 / total_chars as f64) * 100.0).round() as i32
    } else { 
        0 
    };
    
    Ok(FileMetrics {
        filename,
        base_name,
        glyph_count,
        tag_count,
        unusual_chars_count,
        greek_percentage,
        latin_percentage,
    })
}

fn clean_file(input_path: &Path, output_dir: &Path) -> Result<CleaningStats, String> {
    // Get file metadata
    let filename = input_path.file_name()
        .and_then(|name| name.to_str())
        .ok_or_else(|| format!("Invalid filename: {:?}", input_path))?
        .to_string();
    
    // Read file content
    let content = fs::read_to_string(input_path)
        .map_err(|e| format!("Failed to read file: {}", e))?;
    
    // Initialize comment tracking
    let mut comment_count = 0;
    let mut consecutive_comments = 0;
    let mut max_consecutive_comments = 0;
    
    // Step 1: Replace words containing "glyph" with comments if needed
    let mut result = String::new();
    let mut comment_added = false;
    let mut lines_with_replacements = Vec::new();
    
    // Process the file line by line
    for (line_idx, line) in content.lines().enumerate() {
        // Check if this line is a comment already
        let is_comment_line = COMMENT_REGEX.is_match(line);
        
        if is_comment_line {
            consecutive_comments += 1;
            result.push_str(line);
            result.push('\n');
            continue;
        }
        
        // Check if this line has glyph words
        let glyph_matches: Vec<_> = GLYPH_WORD_REGEX.find_iter(line).collect();
        
        if glyph_matches.is_empty() {
            // No glyph words - keep line as is
            result.push_str(line);
            result.push('\n');
            comment_added = false; // Reset comment flag
            consecutive_comments = 0; // Reset consecutive comments counter
            continue;
        }
        
        // This line has glyph words
        let mut new_line = line.to_string();
        let mut total_removed_len = 0;
        
        // Replace glyph words
        for mat in glyph_matches.iter().rev() {
            let removed_text = &line[mat.start()..mat.end()];
            total_removed_len += removed_text.len();
            new_line.replace_range(mat.start()..mat.end(), "");
        }
        
        // If we removed 5 or more characters and don't already have a comment and line is not now empty
        if total_removed_len >= 5 && !comment_added && !new_line.trim().is_empty() {
            if !COMMENT_REGEX.is_match(&new_line) {
                new_line = format!("{} <!-- text-missing -->", new_line);
                comment_added = true;
                comment_count += 1;
                consecutive_comments += 1;
            }
        } else if new_line.trim().is_empty() && total_removed_len >= 5 {
            // Line is now empty, add comment on its own line
            if !comment_added {
                new_line = "<!-- text-missing -->".to_string();
                comment_added = true;
                comment_count += 1;
                consecutive_comments += 1;
            } else {
                // Skip empty line if we already have a comment
                consecutive_comments = 0;
                continue;
            }
        } else if new_line.trim().is_empty() {
            // Line is empty but not from significant removal
            comment_added = false;
            consecutive_comments = 0;
        }
        
        // Update max consecutive comments
        if consecutive_comments > max_consecutive_comments {
            max_consecutive_comments = consecutive_comments;
        }
        
        result.push_str(&new_line);
        result.push('\n');
        
        // Track lines that had replacements
        if total_removed_len > 0 {
            lines_with_replacements.push(line_idx);
        }
    }
    
    // Step 2: Remove unusual characters with comments when needed
    let mut clean_result = String::new();
    comment_added = false;
    consecutive_comments = 0;
    
    // Process the result line by line
    for line in result.lines() {
        // Check if this line is a comment already
        let is_comment_line = COMMENT_REGEX.is_match(line);
        
        if is_comment_line {
            consecutive_comments += 1;
            clean_result.push_str(line);
            clean_result.push('\n');
            continue;
        }
        
        let mut clean_line = String::with_capacity(line.len());
        let mut line_has_unusual = false;
        let mut line_unusual_count = 0;
        
        // Check each character
        for c in line.chars() {
            if UNUSUAL_CHARS.contains(&c) && !GREEK_CHARS.contains(&c) {
                line_has_unusual = true;
                line_unusual_count += 1;
            } else {
                clean_line.push(c);
            }
        }
        
        // Process the cleaned line
        if line_has_unusual && line_unusual_count >= 5 {
            // Line had significant unusual characters
            if !clean_line.trim().is_empty() {
                // Add comment if not already added
                if !COMMENT_REGEX.is_match(&clean_line) {
                    clean_line = format!("{} <!-- text-missing -->", clean_line);
                    comment_added = true;
                    comment_count += 1;
                    consecutive_comments += 1;
                }
            } else {
                // Line is now empty, add comment if needed
                if !comment_added {
                    clean_line = "<!-- text-missing -->".to_string();
                    comment_added = true;
                    comment_count += 1;
                    consecutive_comments += 1;
                } else {
                    // Skip this line as it's empty and we already have a comment
                    continue;
                }
            }
        } else {
            // No significant unusual chars in this line
            comment_added = false;
            consecutive_comments = 0;
        }
        
        // Update max consecutive comments
        if consecutive_comments > max_consecutive_comments {
            max_consecutive_comments = consecutive_comments;
        }
        
        clean_result.push_str(&clean_line);
        clean_result.push('\n');
    }
    
    // Step 3: Remove HTML/XML tags but preserve comments
    let final_result = clean_result.lines().map(|line| {
        // First store all comments in the line
        let mut comments = Vec::new();
        let mut comment_positions = Vec::new();
        
        for comment_match in COMMENT_REGEX.find_iter(line) {
            comments.push(comment_match.as_str().to_string());
            comment_positions.push((comment_match.start(), comment_match.end()));
        }
        
        if !comments.is_empty() {
            // Line has comments - remove all other tags but preserve comments
            let mut result_line = line.to_string();
            
            // Replace all non-comment tags
            for tag_match in ANY_TAG_CLEANING_REGEX.find_iter(line) {
                // Check if this tag is part of a comment
                let is_comment = comment_positions.iter()
                    .any(|(start, end)| tag_match.start() >= *start && tag_match.end() <= *end);
                
                if !is_comment {
                    // Replace with empty string if not a comment
                    result_line = result_line.replace(tag_match.as_str(), "");
                }
            }
            result_line
        } else {
            // No comments, remove all tags
            ANY_TAG_CLEANING_REGEX.replace_all(line, "").to_string()
        }
    }).collect::<Vec<String>>().join("\n");
    
    // Ensure output directory exists
    let output_path = output_dir.join(&filename);
    
    // Write the cleaned file
    fs::write(&output_path, final_result.as_bytes())
        .map_err(|e| format!("Failed to write cleaned file: {}", e))?;
    
    // Return cleaning statistics
    Ok(CleaningStats {
        filename,
        comment_count,
        max_consecutive_comments,
    })
}

#[derive(Debug, Serialize)]
struct ComparisonMetrics {
    filename: String,
    original_greek_percentage: i32,
    cleaned_greek_percentage: i32,
    percentage_increase: i32,
    original_unusual_count: usize,
    cleaned_unusual_count: usize,
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let start_time = Instant::now();
    
    // Define paths
    let markdown_dir = PathBuf::from("/mnt/data/gazette_processing/markdown");
    let output_dir = PathBuf::from("/mnt/data/AI4Deliberation/ΦΕΚ/nomoi/check_badness/extraction_metrics_rs/cleaned_markdown");
    let metrics_csv = PathBuf::from("/mnt/data/AI4Deliberation/ΦΕΚ/nomoi/extraction_metrics_rust.csv");
    let cleaned_metrics_csv = PathBuf::from("/mnt/data/AI4Deliberation/ΦΕΚ/nomoi/extraction_metrics_cleaned_rust.csv");
    let comparison_csv = PathBuf::from("/mnt/data/AI4Deliberation/ΦΕΚ/nomoi/extraction_metrics_comparison.csv");
    let cleaning_stats_csv = PathBuf::from("/mnt/data/AI4Deliberation/ΦΕΚ/nomoi/cleaning_stats.csv");
    
    println!("Finding markdown files in {:?}", markdown_dir);
    
    // Collect all markdown files
    let md_files: Vec<PathBuf> = WalkDir::new(&markdown_dir)
        .into_iter()
        .filter_map(Result::ok)
        .filter(|entry| {
            entry.file_type().is_file() && 
            entry.path().extension().map_or(false, |ext| ext == "md")
        })
        .map(|entry| entry.path().to_path_buf())
        .collect();
    
    let total_files = md_files.len();
    println!("Found {} markdown files", total_files);
    
    // Clean files in parallel and collect cleaning stats
    println!("Cleaning files in parallel...");
    let cleaning_stats: Vec<_> = md_files.par_iter()
        .filter_map(|path| {
            match clean_file(path, &output_dir) {
                Ok(stats) => Some(stats),
                Err(err) => {
                    eprintln!("Error cleaning {:?}: {}", path, err);
                    None
                }
            }
        })
        .collect();
    
    // Save cleaning stats to CSV
    let mut wtr_stats = Writer::from_path(&cleaning_stats_csv)?;
    for stats in &cleaning_stats {
        wtr_stats.serialize(stats)?;
    }
    wtr_stats.flush()?;
    
    println!("Analyzing original files...");
    let original_results: Vec<_> = md_files.par_iter()
        .filter_map(|path| {
            match analyze_file(path) {
                Ok(metrics) => Some(metrics),
                Err(err) => {
                    eprintln!("Error processing {:?}: {}", path, err);
                    None
                }
            }
        })
        .collect();
    
    // Write original results to CSV
    let mut wtr = Writer::from_path(&metrics_csv)?;
    for result in &original_results {
        wtr.serialize(result)?;
    }
    wtr.flush()?;
    
    // Process cleaned files
    println!("Analyzing cleaned files...");
    let cleaned_files: Vec<PathBuf> = WalkDir::new(&output_dir)
        .into_iter()
        .filter_map(Result::ok)
        .filter(|entry| {
            entry.file_type().is_file() && 
            entry.path().extension().map_or(false, |ext| ext == "md")
        })
        .map(|entry| entry.path().to_path_buf())
        .collect();
    
    let cleaned_results: Vec<_> = cleaned_files.par_iter()
        .filter_map(|path| {
            match analyze_file(path) {
                Ok(metrics) => Some(metrics),
                Err(err) => {
                    eprintln!("Error processing cleaned file {:?}: {}", path, err);
                    None
                }
            }
        })
        .collect();
    
    // Write cleaned results to CSV
    let mut wtr_cleaned = Writer::from_path(&cleaned_metrics_csv)?;
    for result in &cleaned_results {
        wtr_cleaned.serialize(result)?;
    }
    wtr_cleaned.flush()?;
    
    // Create comparison data
    let mut comparison_data: Vec<ComparisonMetrics> = Vec::new();
    
    // Create a map for easier lookup
    let mut cleaned_map = std::collections::HashMap::new();
    for metrics in &cleaned_results {
        cleaned_map.insert(&metrics.filename, metrics);
    }
    
    for original in &original_results {
        if let Some(cleaned) = cleaned_map.get(&original.filename) {
            comparison_data.push(ComparisonMetrics {
                filename: original.filename.clone(),
                original_greek_percentage: original.greek_percentage,
                cleaned_greek_percentage: cleaned.greek_percentage,
                percentage_increase: cleaned.greek_percentage - original.greek_percentage,
                original_unusual_count: original.unusual_chars_count,
                cleaned_unusual_count: cleaned.unusual_chars_count,
            });
        }
    }
    
    // Write comparison results to CSV
    let mut wtr_comparison = Writer::from_path(&comparison_csv)?;
    for comparison in &comparison_data {
        wtr_comparison.serialize(comparison)?;
    }
    wtr_comparison.flush()?;
    
    // Print cleaning statistics
    println!("\nCleaning Statistics:");
    let total_comments: usize = cleaning_stats.iter().map(|s| s.comment_count).sum();
    let max_comments_in_file = cleaning_stats.iter().map(|s| s.comment_count).max().unwrap_or(0);
    let avg_comments_per_file = total_comments as f64 / cleaning_stats.len() as f64;
    let max_consecutive = cleaning_stats.iter().map(|s| s.max_consecutive_comments).max().unwrap_or(0);
    
    println!("Total text-missing comments added: {}", total_comments);
    println!("Average comments per file: {:.2}", avg_comments_per_file);
    println!("Maximum comments in a single file: {}", max_comments_in_file);
    println!("Maximum consecutive comments: {}", max_consecutive);
    
    println!("Files with more than 10 consecutive comments: {}", 
             cleaning_stats.iter().filter(|s| s.max_consecutive_comments > 10).count());
    
    // Print summary statistics for original files
    println!("\nOriginal Files Summary:");
    let files_with_glyphs = original_results.iter().filter(|r| r.glyph_count > 0).count();
    let files_with_tags = original_results.iter().filter(|r| r.tag_count > 0).count();
    let files_with_unusual = original_results.iter().filter(|r| r.unusual_chars_count > 0).count();
    
    println!("Files with glyph tags: {} ({:.2}%)", 
             files_with_glyphs, 
             (files_with_glyphs as f64 / original_results.len() as f64) * 100.0);
    
    println!("Files with tags (HTML entities or XML tags): {} ({:.2}%)", 
             files_with_tags, 
             (files_with_tags as f64 / original_results.len() as f64) * 100.0);
    
    println!("Files with unusual characters: {} ({:.2}%)", 
             files_with_unusual, 
             (files_with_unusual as f64 / original_results.len() as f64) * 100.0);
    
    let total_original_glyph_count: usize = original_results.iter().map(|r| r.glyph_count).sum();
    let total_original_unusual_count: usize = original_results.iter().map(|r| r.unusual_chars_count).sum();
    
    println!("Total glyph count: {}", total_original_glyph_count);
    println!("Total unusual character count: {}", total_original_unusual_count);
    
    let avg_original_greek = (original_results.iter().map(|r| r.greek_percentage as i64).sum::<i64>() as f64 / original_results.len() as f64).round() as i32;
    let avg_original_latin = (original_results.iter().map(|r| r.latin_percentage as i64).sum::<i64>() as f64 / original_results.len() as f64).round() as i32;
    
    println!("Average Greek alphabet percentage: {}%", avg_original_greek);
    println!("Average Latin alphabet percentage: {}%", avg_original_latin);
    
    // Print summary statistics for cleaned files
    println!("\nCleaned Files Summary:");
    let cleaned_files_with_glyphs = cleaned_results.iter().filter(|r| r.glyph_count > 0).count();
    let cleaned_files_with_tags = cleaned_results.iter().filter(|r| r.tag_count > 0).count();
    let cleaned_files_with_unusual = cleaned_results.iter().filter(|r| r.unusual_chars_count > 0).count();
    
    println!("Files with glyph tags: {} ({:.2}%)", 
             cleaned_files_with_glyphs, 
             (cleaned_files_with_glyphs as f64 / cleaned_results.len() as f64) * 100.0);
    
    println!("Files with tags (HTML entities or XML tags): {} ({:.2}%)", 
             cleaned_files_with_tags, 
             (cleaned_files_with_tags as f64 / cleaned_results.len() as f64) * 100.0);
    
    println!("Files with unusual characters: {} ({:.2}%)", 
             cleaned_files_with_unusual, 
             (cleaned_files_with_unusual as f64 / cleaned_results.len() as f64) * 100.0);
    
    let total_cleaned_glyph_count: usize = cleaned_results.iter().map(|r| r.glyph_count).sum();
    let total_cleaned_unusual_count: usize = cleaned_results.iter().map(|r| r.unusual_chars_count).sum();
    
    println!("Total glyph count: {}", total_cleaned_glyph_count);
    println!("Total unusual character count: {}", total_cleaned_unusual_count);
    
    let avg_cleaned_greek = (cleaned_results.iter().map(|r| r.greek_percentage as i64).sum::<i64>() as f64 / cleaned_results.len() as f64).round() as i32;
    let avg_cleaned_latin = (cleaned_results.iter().map(|r| r.latin_percentage as i64).sum::<i64>() as f64 / cleaned_results.len() as f64).round() as i32;
    
    println!("Average Greek alphabet percentage: {}%", avg_cleaned_greek);
    println!("Average Latin alphabet percentage: {}%", avg_cleaned_latin);
    
    // Print comparison summary
    println!("\nComparison Summary:");
    println!("Average Greek percentage increase: {:.2}%", 
             comparison_data.iter().map(|c| c.percentage_increase as f64).sum::<f64>() / comparison_data.len() as f64);
    
    println!("Files with significant improvement (>5% increase): {}", 
             comparison_data.iter().filter(|c| c.percentage_increase > 5).count());
    
    // Execution time
    let elapsed = start_time.elapsed();
    println!("\nExecution time: {:.2?}", elapsed);
    
    println!("\nResults saved to:");
    println!("- Original metrics: {:?}", metrics_csv);
    println!("- Cleaned metrics: {:?}", cleaned_metrics_csv);
    println!("- Comparison: {:?}", comparison_csv);
    println!("- Cleaning statistics: {:?}", cleaning_stats_csv);
    
    Ok(())
}
