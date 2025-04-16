# OpenGov.gr Scraping Selectors

This document provides the specific CSS and XPath selectors identified from our analysis of the OpenGov.gr platform.

## Main Consultations List Page

From our analysis of `https://www.opengov.gr/home/category/consultations`, we've identified:

- Each consultation entry appears in a list format
- Consultation items likely have a pattern similar to:
  ```
  <div class="post" or similar container>
    <h3><a href="[consultation-url]">[title]</a></h3>
    <div class="date">[date]</div>
  </div>
  ```

## Consultation Detail Page

From our analysis of `http://www.opengov.gr/ypex/?p=1045`, we've identified:

- Title is in an h3 heading
- Description text follows the title
- Date information is embedded in the introductory text
- Links to articles are listed with comment counts:
  - Format: "X Σχόλια[article title](article url)"
  - or: "Δεν έχουν υποβληθεί σχόλια στο [article title](article url)"

## Article Page

From our analysis of `http://www.opengov.gr/ypex/?p=1044`, we've identified:

- Article title in h3 heading
- Article content follows
- Comments section appears to follow a pattern where each comment has:
  - Author information
  - Date information
  - Comment text

## Next Steps

To refine these selectors, we need to:

1. Examine the HTML structure more closely using browser developer tools
2. Verify selector consistency across different ministries and consultation types
3. Test selectors with sample extraction code
4. Handle pagination for consultations list and comments

## Implementation Priorities

1. Extract the list of all consultations with their basic metadata
2. For each consultation, extract the article links and their comment counts
3. For each article, extract its content and all comments
4. Extract document links (PDFs) from consultation pages

## Edge Cases to Handle

- Different ministries may have slight variations in their page structure
- Comments may be paginated on popular articles
- Some consultations may have unusual formatting or structure
- Greek language encoding considerations
