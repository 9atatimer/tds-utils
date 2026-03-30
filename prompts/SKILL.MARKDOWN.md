# Markdown Editing Skills

> Guidelines for writing and surgically editing Markdown files, especially design docs.

## Formatting Rules (for stable AST parsing)

### Characters

- **No smart quotes**: Use straight quotes (`"` and `'`), never curly (`"` `"` `'` `'`)
- **No smart arrows**: Use `->` not `→`, use `<-` not `←`
- **No em-dashes**: Use `--` not `—`
- **ASCII only in prose**: Avoid Unicode symbols that might render inconsistently

### Structure

- **Blank line after headings**: Always put a blank line between a heading and its content
- **Blank line before lists**: Always put a blank line before bullet or numbered lists
- **Consistent heading levels**: Don't skip levels (e.g., H2 -> H4)
- **No duplicate headings**: Each heading at the same level should be unique within its parent

### Frontmatter (optional)

If using YAML frontmatter:
```yaml
---
title: "Document Title"
status: draft
date: 2025-12-22
related:
  - path/to/other/doc.md
---
```

- Frontmatter goes at the very top of the file
- Use quotes around titles with special characters
- Keep it minimal — only metadata that tools will read

## Surgical Editing with markdown-editor MCP

### When to use markdown-editor

- Single small change to one section in a large file
- Structural operations (move, reorder sections)
- When you need to preserve exact formatting elsewhere in file

### When to use write_file instead

- Multiple scattered changes across a small/medium file (<300 lines)
- Rewriting more than ~30% of the file
- When section IDs keep changing and causing lookup failures

### Tool workflow

1. **list_sections** — Get current section IDs and structure
2. **get_section** — Fetch content of section you want to edit
3. **update_section** — Replace section content (preserves subsections by default)

Section IDs regenerate after each edit, so re-run `list_sections` if you need to make another edit.

### update_section behavior

- Replaces the section's content entirely
- Preserves child sections (subsections) unless you include them in your replacement
- The `content` parameter should include the heading line (e.g., `## My Section\n\nBody text...`)

### insert_section behavior

- `position` parameter is the section index (0-based), not line number
- `heading` parameter is just the title text, not the full markdown heading
- Tool auto-adjusts heading level to match context
- Often creates duplicate/empty sections — verify with `list_sections` after

### delete_section behavior

- Deletes the section and all its subsections by default
- Use `preserve_subsections: true` to keep children (moves them up)

### Common pitfalls

- **Stale section IDs**: IDs change after every edit; always re-fetch
- **Quote escaping**: If your content has quotes, the JSON escaping can cause match failures
- **Position confusion**: `insert_section` position is section index, not line number
- **Empty sections**: Tool sometimes creates empty duplicate headings; clean up with `delete_section`
- **No frontmatter access**: markdown-editor cannot edit YAML frontmatter; use Filesystem:edit_file for that

## Pre-edit checklist

Before editing a Markdown file:

1. Check for smart quotes: `grep -P '[\x{2018}\x{2019}\x{201C}\x{201D}]' file.md`
2. If found, convert them first: `sed -i 's/[""]/"/g; s/['\'']/'\''/g' file.md`
3. Decide: surgical edit or full rewrite?
4. If surgical: use markdown-editor workflow above
5. If rewrite: read file, modify in response, write_file

## Design doc conventions

For project design docs:

- Use YAML frontmatter for metadata (title, status, date, related)
- Start content at H2 (title is in frontmatter)
- Use `(decision)` suffix on headings that record architectural decisions
- Keep a Review Log section at the bottom with dated entries
- Reference other design docs by relative path

## Future enhancements (TODO)

Notes on potential improvements to the markdown-editor MCP server:

### Code block editing

The underlying AST library (`markdown-it-py`) parses code blocks as distinct `Token` objects with type `fence`. However, the MCP tool's section model operates purely on heading boundaries, treating content between headings as opaque text.

**Enhancement idea**: Expose code blocks as editable sub-elements within sections, allowing surgical edits to code snippets without replacing entire section content.

### Frontmatter support

YAML frontmatter is not accessible via markdown-editor — it only operates on heading-based sections.

**Enhancement idea**: Add `get_frontmatter` / `update_frontmatter` tools to read and modify YAML frontmatter directly.

### AST-level operations

The `ast_utils.py` module in the MCP server may already expose lower-level AST access. Worth investigating for:

- Querying specific token types (lists, links, images)
- Fine-grained content manipulation below section level
- Structural validation beyond heading hierarchy
