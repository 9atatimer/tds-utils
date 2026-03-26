;;; tds-v3-ai-author-notes.el --- Notes file parsing for AI author prompts -*- lexical-binding: t; -*-

;;; Commentary:
;; This file handles the parsing and extraction of context information from markdown notes files.
;;
;; IN SCOPE:
;; - Parsing markdown files with TAG:CATEGORY:KEY format
;; - Extracting tagged sections from notes files
;; - Managing notes file paths and directory structure
;; - Caching extracted sections for performance
;; - Constants related to notes file format and tags
;;
;; OUT OF SCOPE:
;; - Context directives processing (handled by tds-v3-ai-author-context)
;; - Prompt assembly (handled by tds-v3-ai-author-prompt)
;; - User-facing commands (handled by tds-v3-ai-author)
;; - Any LaTeX processing or file modification

;;; Code:

(require 'cl-lib)

;; Constants for notes file formats and patterns
(defconst tds-ai-notes-tag-regex "^%\\s-*TAG:%s:%s"
  "Regular expression pattern for finding tagged sections in notes files.
Format with store and key names.")

(defconst tds-ai-notes-section-end-regex "^%\\s-*TAG:\\|^---"
  "Regular expression for section endings (next tag or separator).")

;; Configuration options
(defgroup tds-ai-notes nil
  "Customization group for TDS AI Author Notes."
  :group 'tools)

(defcustom tds-ai-notes-directory "./notes/"
  "Directory containing notes files for context lookups."
  :type 'directory
  :group 'tds-ai-notes)

(defcustom tds-ai-notes-files
  '(("CHARACTER" . "character.md")
    ("PLOT" . "plot.md")
    ("SETTING" . "setting.md")
    ("THEME" . "theme.md")
    ("WORLDBUILDING" . "worldbuilding.md"))
  "Mapping of store names to their corresponding notes files.
Each entry is a cons cell where the car is the store name (as used in
SET/ADD/DROP directives) and the cdr is the filename in `tds-ai-notes-directory`."
  :type '(alist :key-type string :value-type string)
  :group 'tds-ai-notes)

(defcustom tds-ai-notes-debug nil
  "Whether to show debug messages for notes parsing."
  :type 'boolean
  :group 'tds-ai-notes)

;; Internal state
(defvar tds-ai-notes-cache (make-hash-table :test 'equal)
  "Cache for parsed notes sections.")

;; File path handling functions
(defun tds-ai-notes-reset-cache ()
  "Reset the notes cache to empty state."
  (tds-ai-debug "Resetting notes cache")
  (clrhash tds-ai-notes-cache))

(defun tds-ai-notes-get-file-for-store (store)
  "Get the filename for STORE from `tds-ai-notes-files`.
Returns nil if no mapping exists."
  (tds-ai-debug "Looking up file for store: %s" store)
  (let ((filename (cdr (assoc store tds-ai-notes-files))))
    (tds-ai-debug "Found file: %s" (or filename "nil"))
    filename))

(defun tds-ai-notes-file-path (store)
  "Get the full path to the notes file for STORE."
  (tds-ai-debug "Getting file path for store: %s" store)
  (let ((filename (tds-ai-notes-get-file-for-store store)))
    (when filename
      (let ((path (expand-file-name filename tds-ai-notes-directory)))
        (tds-ai-debug "Full path: %s" path)
        path))))

(defun tds-ai-notes-file-exists-p (store)
  "Check if notes file for STORE exists."
  (let ((file-path (tds-ai-notes-file-path store)))
    (let ((exists (and file-path (file-exists-p file-path))))
      (tds-ai-debug "Checking if file exists for %s: %s" store (if exists "yes" "no"))
      exists)))

(defun tds-ai-notes-make-cache-key (store key)
  "Create a cache key from STORE and KEY."
  (let ((cache-key (format "%s:%s" store key)))
    (tds-ai-debug "Created cache key: %s" cache-key)
    cache-key))

;; Section extraction functions
(defun tds-ai-notes-find-section-end (start-pos pattern end-pos)
  "Find the end of a section starting at START-POS.
Searches for PATTERN until END-POS."
  (tds-ai-debug "Finding section end from %s with pattern %s" start-pos pattern)
  (save-excursion
    (goto-char start-pos)
    (let ((end (if (re-search-forward pattern end-pos t)
                   (match-beginning 0)
                 end-pos)))
      (tds-ai-debug "Found section end at %s" end)
      end)))

(defun tds-ai-notes-extract-section-content (start-pos end-pos)
  "Extract and trim content between START-POS and END-POS."
  (tds-ai-debug "Extracting content from %s to %s" start-pos end-pos)
  (save-excursion
    (let ((content (buffer-substring-no-properties
                    (progn
                      (goto-char start-pos)
                      (forward-line 1)
                      (point))
                    end-pos)))
      (let ((trimmed (string-trim content)))
        (tds-ai-debug "Extracted %d chars, trimmed to %d chars"
                           (length content) (length trimmed))
        trimmed))))

(defun tds-ai-notes-extract-section (store key)
  "Extract sections tagged with STORE:KEY from the appropriate notes file.
Returns a list of strings, each being the content of a matching section."
  (tds-ai-debug "Extracting sections for %s:%s" store key)
  (let ((cache-key (tds-ai-notes-make-cache-key store key)))
    ;; Check cache first
    (if (gethash cache-key tds-ai-notes-cache)
        (progn
          (tds-ai-debug "Cache hit for %s" cache-key)
          (gethash cache-key tds-ai-notes-cache))

      ;; Not in cache, extract from file
      (tds-ai-debug "Cache miss for %s, extracting from file" cache-key)
      (if (not (tds-ai-notes-file-exists-p store))
          (progn
            (message "Warning: Notes file for store '%s' does not exist" store)
            (tds-ai-debug "File does not exist for store %s" store)
            nil)
        (let ((file-path (tds-ai-notes-file-path store))
              (tag-pattern (format tds-ai-notes-tag-regex store key))
              (sections '()))

          (tds-ai-debug "Reading file: %s" file-path)
          (with-temp-buffer
            (insert-file-contents file-path)
            (goto-char (point-min))
            (tds-ai-debug "Searching for pattern: %s" tag-pattern)

            ;; Find all sections with matching tag
            (let ((section-count 0))
              (while (re-search-forward tag-pattern nil t)
                (setq section-count (1+ section-count))
                (tds-ai-debug "Found section %d at line %d"
                                    section-count (line-number-at-pos))
                (let* ((section-start (line-beginning-position))
                       (section-end (tds-ai-notes-find-section-end
                                    section-start
                                    tds-ai-notes-section-end-regex
                                    (point-max)))
                       (section-content (tds-ai-notes-extract-section-content
                                        section-start
                                        section-end)))

                  ;; Add to sections list if non-empty
                  (unless (string-empty-p section-content)
                    (tds-ai-debug "Adding section content (%d chars)"
                                       (length section-content))
                    (push section-content sections))

                  ;; Go back to section end to continue search
                  (goto-char section-end)))

              (tds-ai-debug "Found %d total sections" section-count))

            ;; Cache the result
            (let ((result (nreverse sections)))
              (tds-ai-debug "Caching %d sections for %s" (length result) cache-key)
              (puthash cache-key result tds-ai-notes-cache)
              result)))))))

(defun tds-ai-notes-get-all-keys ()
  "Get a list of all available STORE:KEY combinations from notes files."
  (tds-ai-debug "Getting all available STORE:KEY combinations")
  (let ((keys '()))
    (dolist (store-file tds-ai-notes-files)
      (let* ((store (car store-file))
             (file-path (tds-ai-notes-file-path store)))
        (tds-ai-debug "Checking %s in file %s" store file-path)
        (when (file-exists-p file-path)
          (with-temp-buffer
            (insert-file-contents file-path)
            (goto-char (point-min))
            (let ((file-keys 0))
              (while (re-search-forward "^%\\s-*TAG:\\([A-Z_]+\\):\\([A-Z_]+\\)" nil t)
                (let ((found-store (match-string 1))
                      (key (match-string 2)))
                  (when (string= found-store store)
                    (setq file-keys (1+ file-keys))
                    (tds-ai-debug "Found key in file: %s:%s" found-store key)
                    (push (cons store key) keys))))
              (tds-ai-debug "Found %d keys in file %s" file-keys file-path))))))
    (let ((result (nreverse keys)))
      (tds-ai-debug "Found %d total keys across all files" (length result))
      result)))

;;; TODO: Future enhancements to consider:
;; 1. Cross-file references: Allow notes to reference other notes
;; 2. Template variables with qualifiers: {{CHARACTER:TRIM:100}}
;; 3. Version tracking: Support specific versions of notes

(provide 'tds-v3-ai-author-notes)
;;; tds-v3-ai-author-notes.el ends here
