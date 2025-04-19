# OpenGov.gr Deliberation Data Schema

## Database Structure Relations

### Legislation
- A legislation has a unique identifier
- A legislation has a title
- A legislation has a ministry
- A legislation has a URL
- A legislation has a description/content
- A legislation has a deliberation start date
- A legislation has a deliberation end date 
- A legislation has many articles
- A legislation has one expected changes document

### Expected Changes Document
- An expected changes document has a unique identifier
- An expected changes document belongs to one legislation
- An expected changes document has a PDF URL
- An expected changes document has extracted content (after PDF processing)

### Article
- An article has a unique identifier
- An article belongs to one legislation
- An article has a title
- An article has content
- An article has a URL
- An article has many comments

### Comment
- A comment has a unique identifier
- A comment belongs to one article
- A comment has an author username
- A comment has a post date
- A comment has content

## Pagination Handling
- The main legislation listing page has pagination
- Each page contains approximately 20 legislations
- There are around 60 pages in total
- We need to detect if a "next page" exists and follow it

## HTML Selectors (To Be Filled)

### Main Listing Page
- Legislation container selector: `___________________`
- Legislation title selector: `___________________`
- Legislation URL selector: `___________________`
- Legislation ministry selector: `___________________`
- Pagination "next page" selector: `___________________`

### Legislation Detail Page
- Legislation title selector: `___________________`
- Legislation description/content selector: `___________________`
- Deliberation start date selector: `___________________`
- Deliberation end date selector: `___________________`
- Expected changes PDF URL selector: `___________________`
- Articles list container selector: `___________________`
- Individual article link selector: `___________________`

### Article Page
- Article title selector: `___________________`
- Article content selector: `___________________`
- Comments container selector: `___________________`
- Individual comment selector: `___________________`
- Comment author selector: `___________________`
- Comment date selector: `___________________`
- Comment content selector: `___________________`
