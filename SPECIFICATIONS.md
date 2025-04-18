# OpenGov.gr Deliberation Scraper Specifications

This document outlines the technical specifications for scraping deliberation data from the OpenGov.gr platform.

## Website Structure Analysis

### Main Consultations Page
- URL: `https://www.opengov.gr/home/category/consultations`
- List of consultations is located in the main content area
- Each consultation item contains:
  - Title: Heading with link to consultation page
  - Date: Typically displayed in format "DD Month, YYYY"
  - Ministry: Identified from the URL structure or page heading

### Individual Consultation Page
- URL Pattern: `http://www.opengov.gr/{ministry-code}/?p={post-id}`
  - Example: `http://www.opengov.gr/ypex/?p=1045`
- Main elements:
  - Title: `<h3>` heading containing consultation title
  - Description/Intro: Text content following the title
  - Minister's message: Introductory message from the minister about the legislation
  - Ministry: Available in the header
  - Start/End dates: Typically in the introductory text
  - Deliberation status: Finished or ongoing (determined by dates or status indicators)
  - Document links: PDF files (νομοσχέδιο, εκθέσεις, etc.)
  - Result PDF: For finished deliberations, a PDF containing ministry's response/summary
  - Article list: Links to individual articles of the legislation

### Article Pages
- URL Pattern: `http://www.opengov.gr/{ministry-code}/?p={article-id}`
  - Example: `http://www.opengov.gr/ypex/?p=1044`
- Main elements:
  - Article title/number: In heading
  - Article text content
  - Comment count: Usually shown as "X Σχόλια"
  - Comments section: List of public comments with author and date

## CSS/XPath Selectors

### Main Consultation List Page
- Consultation items: `.post` or similar container class
- Consultation titles: `.post h3 a` or `.entry-title a`
- Dates: Typically near the title, often in a `.date` or metadata class
- Pagination: Links at bottom of page, typically `.pagination a`

### Individual Consultation Page
- Title: `h3.entry-title` or similar
- Content: `.entry-content` or main content container
- Document links: `a[href$=".pdf"]` within content
- Article links: Look for links to individual articles

### Article Page
- Article title: `h3.entry-title` or similar
- Article content: `.entry-content p` (paragraphs of article text)
- Comment count: Text containing "X Σχόλια"
- Comments: `.comment` or similar container class
  - Comment author: `.comment-author` or similar
  - Comment date: `.comment-date` or similar
  - Comment text: `.comment-content` or similar

## Data Models

### Ministry
```python
class Ministry:
    code: str              # Ministry code in URL (e.g., 'ministryofjustice')
    name: str              # Full ministry name
    url: str               # Base URL to the ministry's consultation page
    consultations: List[Consultation]  # Consultations from this ministry
```

### Consultation
```python
class Consultation:
    id: str                # Post ID
    title: str             # Consultation title
    start_minister_message: str  # Initial message from the minister (kickoff)
    end_minister_message: str    # Final message from the minister (only for finished deliberations)
    start_date: datetime   # Start date of consultation
    end_date: datetime     # End date of consultation
    is_finished: bool      # Whether deliberation is finished or ongoing
    url: str               # Full URL to consultation
    description: str       # Introduction/description text
    documents: List[Document]  # Associated documents

    total_comments: int    # Total number of comments across all articles
    accepted_comments: int # Number of accepted comments that were published
    articles: List[Article]    # Articles of legislation
    ministry_id: str       # Reference to parent ministry
```

### Article
```python
class Article:
    id: str                # Article post ID
    title: str             # Article title/number
    content: str           # Article text content
    url: str               # URL to the article page
    comments: List[Comment]    # Comments on this article
```

### Comment
```python
class Comment:
    id: str                # Comment ID
    username: str          # Comment username
    date: datetime         # Date/time of comment
    content: str           # Comment text
    article_id: str        # ID of parent article
```

### Document
```python
class Document:
    id: str                # Document ID
    title: str             # Document title
    url: str               # URL to document (usually PDF)
    type: str              # Type: 'law_draft' (Σχέδιο Νόμου), 'analysis' (Ανάλυση Συνεπειών Ρύθμισης),
                          # 'deliberation_report' (ΕΚΘΕΣΗ ΕΠΙ ΤΗΣ ΔΗΜΟΣΙΑΣ ΔΙΑΒΟΥΛΕΥΣΗΣ), or 'other'
    consultation_id: str   # ID of parent consultation
```

## Database Schema

### Ministries Table
```
id: Integer (Primary Key)
code: String (100) [Not Null, Unique]
name: String (255) [Not Null]
url: String (255) [Not Null]
```

### Consultations Table
```
id: Integer (Primary Key)
post_id: String (50) [Not Null]
title: String (500) [Not Null]
start_minister_message: Text
end_minister_message: Text
start_date: DateTime
end_date: DateTime
is_finished: Boolean [Nullable]
url: String (255) [Not Null, Unique]
total_comments: Integer [Default: 0]
accepted_comments: Integer [Nullable]
ministry_id: Integer [Foreign Key to ministries.id]
```

### Articles Table
```
id: Integer (Primary Key)
post_id: String (50) [Not Null]
title: String (500) [Not Null]
content: Text
raw_html: Text
url: String (255) [Not Null, Unique]
consultation_id: Integer [Foreign Key to consultations.id]
```

### Comments Table
```
id: Integer (Primary Key)
comment_id: String (50)
username: String (255) [Not Null]
date: DateTime
content: Text [Not Null]
article_id: Integer [Foreign Key to articles.id]
```

### Documents Table
```
id: Integer (Primary Key)
title: String (255) [Not Null]
url: String (255) [Not Null, Unique]
type: String (100)
consultation_id: Integer [Foreign Key to consultations.id]
```

## Implementation Strategy

1. Start with a basic scraper for the consultation list page
2. Build parsers for individual consultation pages
3. Implement article and comment extraction
4. Add document downloading capability
5. Create data export utilities
6. Build search and filtering tools

## Challenges and Considerations

- The site structure may vary between different ministry sections
- Pagination handling for large consultation lists
- Character encoding (Greek language)
- PDF document parsing for deeper analysis
- Rate limiting to avoid overloading the server
- Data validation and cleaning
- Handling of different comment formats
- Determining deliberation status accurately
- Downloading and processing result PDFs for finished deliberations
