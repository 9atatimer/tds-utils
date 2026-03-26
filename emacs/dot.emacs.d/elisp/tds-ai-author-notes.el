;;; tds-ai-author-notes.el --- Notes parser for AI author assistance -*- lexical-binding: t; -*-

;;; Commentary:
;; Parses markdown notes files to build relationship graphs between entities
;; Enhances AI prompts with relevant relationship context
;; Works alongside tds-ai-author.el and tds-ai-author-context-template.el

;;; Code:
(require 'cl-lib)
(require 'markdown-mode nil t) ;; Optional but helpful for markdown parsing

;; Configuration variables
(defcustom tds-notes-directory nil
  "Directory containing markdown notes files.  Will be determined lazily."
  :type 'string
  :group 'tds-ai-author)

(defcustom tds-notes-files '("characters.md" "settings.md" "plot.md")
  "List of markdown files to parse for relationship data."
  :type '(repeat string)
  :group 'tds-ai-author)

(defcustom tds-notes-categories '("CHARACTER" "SETTING" "PLOT")
  "Valid categories for entity relationships."
  :type '(repeat string)
  :group 'tds-ai-author)

(defcustom tds-notes-relationship-types '("CHARACTERS" "SETTINGS" "PLOT")
  "Relationship types as they appear in notes files (usually plural forms)."
  :type '(repeat string)
  :group 'tds-ai-author)

;; Internal variables
(defvar tds-notes-graph nil
  "Relationship graph mapping entities to their descriptions and relationships.")

(defvar tds-notes-last-parse-time nil
  "Timestamp of the last time the notes files were parsed.")

;; Helper functions
(defun tds-notes-get-directory ()
  "Get notes directory, determining it if not yet set."
  (unless tds-notes-directory
    (let ((project-root (ignore-errors (project-root (project-current t)))))
      (setq tds-notes-directory
            (if project-root
                (expand-file-name "notes" project-root)
              (expand-file-name "notes" default-directory)))))
  tds-notes-directory)

(defun tds-notes-file-path (filename)
  "Return full path to FILENAME in notes directory."
  (expand-file-name filename (tds-notes-get-directory)))

(defun tds-notes-file-modified-time (filename)
  "Return the last modification time of FILENAME."
  (let ((file-path (tds-notes-file-path filename)))
    (when (file-exists-p file-path)
      (nth 5 (file-attributes file-path)))))

(defun tds-notes-files-modified-since-last-parse ()
  "Check if any notes files have been modified since the last parse."
  (or (null tds-notes-last-parse-time)
      (cl-some (lambda (file)
                 (let ((mod-time (tds-notes-file-modified-time file)))
                   (and mod-time (time-less-p tds-notes-last-parse-time mod-time))))
               tds-notes-files)))

(defun tds-notes-normalize-entity-name (entity)
  "Normalize ENTITY name by trimming whitespace and converting to lowercase."
  (let ((trimmed (downcase (string-trim entity))))
    ;; Remove any parentheses if present
    (replace-regexp-in-string "[()]" "" trimmed)))

(defun tds-notes-parse-entity-line (line)
  "Parse an entity definition line like '# EntityName'."
  (when (string-match "^#\\s-+\\(.+\\)$" line)
    (string-trim (match-string 1 line))))

(defun tds-notes-parse-relationship-type-line (line)
  "Parse a relationship type line like '* CATEGORY'."
  (when (string-match "^\\s-*\\*\\s-+\\([A-Z]+\\)$" line)
    (match-string 1 line)))

(defun tds-notes-parse-relationship-line (line)
  "Parse a relationship line like '* EntityName: description'."
  (when (string-match "^\\s-*\\*\\s-+\\([^:]+\\):\\s-*\\(.+\\)$" line)
    (cons (string-trim (match-string 1 line))
          (string-trim (match-string 2 line)))))

(defun tds-notes-clean-context-marker (marker)
  "Clean a context marker like 'CHARACTER[Entity - description]'.
Extracts category and entity name (before any dash)."
  (when (string-match "\\([A-Z]+\\)\\[\\([^]]+\\)\\]" marker)
    (let* ((category (match-string 1 marker))
           (content (match-string 2 marker))
           (entity (if (string-match "^\\s-*\\([^-]+?\\)\\s-*-" content)
                      (match-string 1 content)
                    content)))
      (cons category (tds-notes-normalize-entity-name (string-trim entity))))))

;; Core parsing functions
(defun tds-notes-parse-file (filename category)
  "Parse FILENAME and extract entities and relationships for CATEGORY."
  (message "Parsing notes file: %s (Category: %s)" filename category)
  (with-temp-buffer
    (insert-file-contents (tds-notes-file-path filename))
    (let ((lines (split-string (buffer-string) "\n"))
          (current-entity nil)
          (current-description "")
          (current-rel-type nil)
          (in-description t)
          (entities '()))

      (dolist (line lines)
        (cond
         ;; New entity
         ((string-match-p "^#\\s-+" line)
          (when current-entity
            (push (list (car current-entity)
                        (string-trim current-description)
                        category
                        (cdr current-entity))
                  entities))
          (setq current-entity (cons (tds-notes-parse-entity-line line) nil)
                current-description ""
                in-description t
                current-rel-type nil))

         ;; Relationship type marker
         ((and (string-match-p "^\\s-*\\*\\s-+[A-Z]+$" line)
               (member (tds-notes-parse-relationship-type-line line) tds-notes-relationship-types))
          (setq current-rel-type (tds-notes-parse-relationship-type-line line)
                in-description nil))

         ;; Relationship entry
         ((and (not in-description)
               current-rel-type
               (string-match-p "^\\s-*\\*\\s-+[^:]+:" line))
          (let ((rel (tds-notes-parse-relationship-line line)))
            (when rel
              (push (list (car rel)
                          (cdr rel)
                          current-rel-type)
                    (cdr current-entity)))))

         ;; Part of entity description (non-empty line that's not a list item)
         ((and in-description (not (string-match-p "^\\s-*\\*" line)) (not (string-empty-p (string-trim line))))
          (setq current-description (concat current-description
                                           (if (string-empty-p current-description) "" " ")
                                           (string-trim line))))))

      ;; Add the last entity
      (when current-entity
        (push (list (car current-entity)
                    (string-trim current-description)
                    category
                    (cdr current-entity))
              entities))

      ;; Return the parsed entities
      (nreverse entities))))

(defun tds-notes-build-graph ()
  "Build or rebuild the relationship graph from notes files."
  (message "Building notes relationship graph...")
  (setq tds-notes-graph (make-hash-table :test 'equal))

  ;; Parse each notes file
  (dolist (file-info (list (cons "characters.md" "CHARACTER")
                           (cons "settings.md" "SETTING")
                           (cons "plot.md" "PLOT")))
    (let ((filename (car file-info))
          (category (cdr file-info)))
      (when (file-exists-p (tds-notes-file-path filename))
        (dolist (entity-data (tds-notes-parse-file filename category))
          (let ((entity-name (nth 0 entity-data))
                (description (nth 1 entity-data))
                (category (nth 2 entity-data))
                (relationships (nth 3 entity-data)))
            ;; Store in graph
            (puthash (format "%s:%s" category (tds-notes-normalize-entity-name entity-name))
                     (list :name entity-name
                           :category category
                           :description description
                           :relationships relationships)
                     tds-notes-graph))))))

  (setq tds-notes-last-parse-time (current-time))
  (message "Notes graph built with %d entities" (hash-table-count tds-notes-graph))
  tds-notes-graph)

(defun tds-notes-ensure-graph ()
  "Ensure the relationship graph is built and up to date."
  (when (or (null tds-notes-graph)
            (tds-notes-files-modified-since-last-parse))
    (when (file-directory-p (tds-notes-get-directory))
      (tds-notes-build-graph)))
  tds-notes-graph)

;; Context extraction functions
(defun tds-notes-find-entity (category entity-name)
  "Find entity with CATEGORY and ENTITY-NAME in the graph."
  (tds-notes-ensure-graph)
  (gethash (format "%s:%s" category (tds-notes-normalize-entity-name entity-name))
           tds-notes-graph))

(defun tds-notes-extract-relationships (context-markers)
  "Extract relevant relationships based on CONTEXT-MARKERS."
  (message "Extracting relationships for context markers: %s" context-markers)
  (let ((related-info '())
        (processed-markers '())
        (active-entities '()))

    ;; First pass: Process context markers and collect active entities
    (dolist (marker context-markers)
      (let* ((marker-parts (tds-notes-clean-context-marker marker))
             (category (car marker-parts))
             (entity-name (cdr marker-parts)))
        (when (and category entity-name)
          (push (cons category entity-name) active-entities)
          (push marker processed-markers))))

    ;; Second pass: Find relationships between active entities
    (dolist (entity-info active-entities)
      (let* ((category (car entity-info))
             (entity-name (cdr entity-info))
             (entity-data (tds-notes-find-entity category entity-name)))
        (when entity-data
          ;; For each relationship this entity has
          (dolist (relationship (plist-get entity-data :relationships))
            (let* ((rel-entity (nth 0 relationship))
                   (rel-desc (nth 1 relationship))
                   (rel-type (nth 2 relationship))
                   ;; Convert relationship type (plural) to category (singular)
                   (rel-category (cond
                                  ((string= rel-type "CHARACTERS") "CHARACTER")
                                  ((string= rel-type "SETTINGS") "SETTING")
                                  (t rel-type))))
              ;; Check if this relationship connects to an active entity
              (when (cl-member (cons rel-category rel-entity) active-entities
                             :test (lambda (a b) (and (string= (car a) (car b))
                                                    (string= (cdr a) (cdr b)))))
                (push (format "* %s - %s: %s"
                             entity-name
                             rel-entity
                             rel-desc)
                      related-info)))))))

    ;; Return the formatted related info
    (nreverse related-info)))

;; Main entry point
(defun tds-notes-get-context (context-markers)
  "Generate notes context from CONTEXT-MARKERS for inclusion in AI prompt."
  (message "Generating notes context from markers: %s" context-markers)
  (when (file-directory-p (tds-notes-get-directory))
    (let ((relationships (tds-notes-extract-relationships context-markers)))
      (if relationships
          (concat "NOTES:\n" (mapconcat #'identity relationships "\n"))
        ""))))

;; Debug functions
(defun tds-notes-debug-graph ()
  "Display the current relationship graph for debugging."
  (interactive)
  (tds-notes-ensure-graph)
  (with-current-buffer (get-buffer-create "*Notes Graph Debug*")
    (erase-buffer)
    (insert "=== NOTES RELATIONSHIP GRAPH ===\n\n")
    (maphash (lambda (key value)
               (insert (format "ENTITY: %s\n" key))
               (insert (format "  Name: %s\n" (plist-get value :name)))
               (insert (format "  Category: %s\n" (plist-get value :category)))
               (insert (format "  Description: %s\n" (plist-get value :description)))
               (insert "  Relationships:\n")
               (dolist (rel (plist-get value :relationships))
                 (insert (format "    * %s: %s (%s)\n"
                                (nth 0 rel) (nth 1 rel) (nth 2 rel))))
               (insert "\n"))
             tds-notes-graph)
    (display-buffer (current-buffer))))

(defun tds-notes-test ()
  "Test notes processing with visible feedback."
  (interactive)
  (message "Starting notes test...")
  (let ((graph (tds-notes-ensure-graph)))
    (message "Graph built with %d entities" (hash-table-count graph))

    ;; Print all keys in the graph
    (message "All keys in graph:")
    (let ((all-keys '()))
      (maphash (lambda (key value) (push key all-keys)) graph)
      (message "%S" all-keys))

    ;; Try different case variations
    (let ((shera1 (tds-notes-find-entity "CHARACTER" "shera"))
          (shera2 (tds-notes-find-entity "CHARACTER" "Shera"))
          (shera3 (tds-notes-find-entity "CHARACTER" "SHERA"))
          (heman1 (tds-notes-find-entity "CHARACTER" "heman"))
          (heman2 (tds-notes-find-entity "CHARACTER" "Heman"))
          (heman3 (tds-notes-find-entity "CHARACTER" "HEMAN")))

      (message "Shera (lowercase): %s" (if shera1 "YES" "NO"))
      (message "Shera (capitalized): %s" (if shera2 "YES" "NO"))
      (message "Shera (uppercase): %s" (if shera3 "YES" "NO"))
      (message "Heman (lowercase): %s" (if heman1 "YES" "NO"))
      (message "Heman (capitalized): %s" (if heman2 "YES" "NO"))
      (message "Heman (uppercase): %s" (if heman3 "YES" "NO"))

      (tds-notes-debug-graph))))

(defun tds-notes-test-extraction (markers)
  "Test relationship extraction with MARKERS."
  (interactive "sEnter context markers (comma-separated): ")
  (let* ((marker-list (split-string markers ","))
         (context (tds-notes-get-context marker-list)))
    (with-current-buffer (get-buffer-create "*Notes Context Test*")
      (erase-buffer)
      (insert "=== CONTEXT MARKERS ===\n")
      (dolist (marker marker-list)
        (insert (format "* %s\n" (string-trim marker))))
      (insert "\n=== EXTRACTED CONTEXT ===\n")
      (insert context)
      (display-buffer (current-buffer)))))

;; Integration with existing AI author system
(defun tds-notes-enhance-prompt (original-prompt context-markers)
  "Enhance ORIGINAL-PROMPT with notes context from CONTEXT-MARKERS."
  (let ((notes-context (tds-notes-get-context context-markers)))
    (if (string-empty-p notes-context)
        original-prompt  ; No notes context to add
      (concat original-prompt "\n" notes-context))))

;; Integration with the context template system
(defun tds-notes-context-from-buffer ()
  "Extract all context markers from the current buffer."
  (let ((markers '())
        (prefix (concat "^" (regexp-quote tds-context-prefix)))
        (begin (regexp-quote tds-context-begin-marker))
        (end (regexp-quote tds-context-end-marker)))
    (save-excursion
      (goto-char (point-min))
      (while (re-search-forward (concat prefix "\\([A-Z]+\\)" begin) nil t)
        (let ((category (match-string 1))
              (marker-start (match-end 0))
              (marker-end nil))
          (when (search-forward end nil t)
            (setq marker-end (match-beginning 0))
            (when (and marker-start marker-end)
              (push (format "%s[%s]"
                           category
                           (buffer-substring-no-properties marker-start marker-end))
                    markers))))))
    markers))

;; Initialize system
(defun tds-notes-initialize ()
  "Initialize the notes system."
  (interactive)
  (unless (file-directory-p (tds-notes-get-directory))
    (message "Creating notes directory at %s" (tds-notes-get-directory))
    (make-directory (tds-notes-get-directory) t))
  (tds-notes-build-graph)
  (message "Notes system initialized with %d entities" (hash-table-count tds-notes-graph)))

(provide 'tds-ai-author-notes)
;;; tds-ai-author-notes.el ends here
