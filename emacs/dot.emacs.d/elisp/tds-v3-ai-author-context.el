;;; tds-v3-ai-author-context.el --- Context extraction for AI author prompts -*- lexical-binding: t; -*-

;;; Commentary:
;; This file handles the extraction of context from LaTeX documents,
;; including directives, surrounding text, and building the context store.
;;
;; IN SCOPE:
;; - Extracting SET/ADD/DROP directives from documents
;; - Processing these directives to build a context store
;; - Extracting surrounding text (mise-en-scene)
;; - Handling airesponse blocks with enabled/disabled status
;; - Constants related to directive formats and patterns
;;
;; OUT OF SCOPE:
;; - Notes file parsing (handled by tds-v3-ai-author-notes)
;; - Prompt assembly (handled by tds-v3-ai-author-prompt)
;; - User-facing commands (handled by tds-v3-ai-author)
;; - LLM interaction

;;; Code:

(require 'cl-lib)
(require 'tds-v3-ai-author-notes)

;; Constants for directive and content patterns
(defconst tds-ai-context-directive-regex "^%\\s-*\\([A-Z]+:[A-Z_]+:[A-Z_]+\\(?::[^%\n]*\\)?\\)"
  "Regular expression to match directive lines in the document.")

(defconst tds-ai-context-directive-parse-regex "^\\([A-Z]+\\):\\([A-Z_]+\\):\\([A-Z_]+\\)\\(?::\\(.*\\)\\)?$"
  "Regular expression to parse directive components.")

(defconst tds-ai-context-legacy-tag-regex "^%\\s-*\\([A-Z_]+\\)\\[\\([^]]*\\)\\]"
  "Regular expression to match legacy format tags.")

(defconst tds-ai-context-airesponse-regex "\\\\begin{airesponse}\\(\\[\\([^]]*\\)\\]\\)?"
  "Regular expression to match airesponse environment start with optional parameter.")

(defconst tds-ai-context-airesponse-end "\\\\end{airesponse}"
  "String marking the end of an airesponse environment.")

(defconst tds-ai-context-comment-regex "^%"
  "Regular expression to match comment lines.")

;; Configuration options
(defgroup tds-ai-context nil
  "Customization group for TDS AI Author Context."
  :group 'tools)

(defcustom tds-ai-context-max-narrative-tokens 1000
  "Maximum number of characters to include from surrounding narrative context."
  :type 'integer
  :group 'tds-ai-context)

;; Internal state
(defvar tds-ai-context-store (make-hash-table :test 'equal)
  "KV store for context management across the document.")

;; Store management functions
(defun tds-ai-context-reset-store ()
  "Reset the context store to empty state."
  (tds-ai-debug "Resetting context store")
  (clrhash tds-ai-context-store))

(defun tds-ai-context-make-store-key (store key)
  "Create a store key from STORE and KEY components."
  (let ((store-key (format "%s:%s" store key)))
    (tds-ai-debug "Created store key: %s" store-key)
    store-key))

(defun tds-ai-context-store-add (store key value)
  "Add VALUE to STORE:KEY in the context store."
  (let ((store-key (tds-ai-context-make-store-key store key)))
    (tds-ai-debug "Adding to %s: %s" store-key (substring value 0 (min 30 (length value))))
    (let ((existing (gethash store-key tds-ai-context-store '())))
      (puthash store-key
               (append existing (list value))
               tds-ai-context-store))))

(defun tds-ai-context-store-set (store key value)
  "Set STORE:KEY to VALUE in the context store."
  (let ((store-key (tds-ai-context-make-store-key store key)))
    (tds-ai-debug "Setting %s to %s"
                         store-key
                         (if value
                             (substring value 0 (min 30 (length value)))
                           "nil"))
    (puthash store-key
             (if value (list value) '())
             tds-ai-context-store)))

(defun tds-ai-context-store-drop (store key &optional value)
  "Drop STORE:KEY or specific VALUE from the context store."
  (let ((store-key (tds-ai-context-make-store-key store key)))
    (if value
        (progn
          (tds-ai-debug "Dropping specific value from %s" store-key)
          (let ((existing (gethash store-key tds-ai-context-store '())))
            (puthash store-key
                     (cl-remove value existing :test 'string=)
                     tds-ai-context-store)))
      (progn
        (tds-ai-debug "Dropping entire key %s" store-key)
        (remhash store-key tds-ai-context-store)))))

;; Directive parsing and processing
(defun tds-ai-context-parse-directive (directive)
  "Parse a directive string in format VERB:STORE:KEY[:VALUE].
Returns a list (verb store key value) or nil if invalid format."
  (tds-ai-debug "Parsing directive: %s" directive)
  (when (string-match tds-ai-context-directive-parse-regex directive)
    (let ((verb (match-string 1 directive))
          (store (match-string 2 directive))
          (key (match-string 3 directive))
          (value (match-string 4 directive)))
      (tds-ai-debug "Parsed: VERB=%s, STORE=%s, KEY=%s, VALUE=%s"
                          verb store key (or value "nil"))
      (list verb store key value))))

(defun tds-ai-context-process-directive (directive)
  "Process a single directive in format VERB:STORE:KEY[:VALUE]."
  (tds-ai-debug "Processing directive: %s" directive)
  (let ((parsed (tds-ai-context-parse-directive directive)))
    (when parsed
      (let ((verb (nth 0 parsed))
            (store (nth 1 parsed))
            (key (nth 2 parsed))
            (value (nth 3 parsed)))

        (cond
         ;; SET: Replace existing value(s) with new one
         ((string= verb "SET")
          (tds-ai-debug "SET operation for %s:%s" store key)
          (tds-ai-context-store-set store key value))

         ;; ADD: Append new value to existing ones
         ((string= verb "ADD")
          (tds-ai-debug "ADD operation for %s:%s" store key)
          (if value
              (tds-ai-context-store-add store key value)
            ;; If no explicit value, try to pull from notes
            (tds-ai-context-add-from-notes store key)))

         ;; DROP: Remove specific key or subkey
         ((string= verb "DROP")
          (tds-ai-debug "DROP operation for %s:%s" store key)
          (tds-ai-context-store-drop store key value)))))))

(defun tds-ai-context-add-from-notes (store key)
  "Add content from notes file based on STORE and KEY to the context store."
  (tds-ai-debug "Adding from notes: %s:%s" store key)
  (let ((sections (tds-ai-notes-extract-section store key)))
    (tds-ai-debug "Found %d sections in notes" (length sections))
    (when sections
      (let ((store-key (tds-ai-context-make-store-key store key)))
        (let ((existing (gethash store-key tds-ai-context-store '())))
          (tds-ai-debug "Adding %d sections to existing %d values"
                              (length sections) (length existing))
          (puthash store-key
                   (append existing sections)
                   tds-ai-context-store))))))

;; Directive collection functions
(defun tds-ai-context-collect-tags (start end)
  "Collect and process all context tags between START and END."
  (tds-ai-debug "Collecting tags from %s to %s" start end)
  (save-excursion
    (goto-char start)
    (let ((count 0))
      (while (re-search-forward tds-ai-context-directive-regex end t)
        (setq count (1+ count))
        (tds-ai-debug "Found directive %d: %s" count (match-string 1))
        (tds-ai-context-process-directive (match-string 1)))
      (tds-ai-debug "Processed %d directives total" count))))

(defun tds-ai-context-collect-legacy-tags (start end)
  "Collect and process legacy tags (% KEY[...]) between START and END."
  (tds-ai-debug "Collecting legacy tags from %s to %s" start end)
  (save-excursion
    (goto-char start)
    (let ((count 0))
      (while (re-search-forward tds-ai-context-legacy-tag-regex end t)
        (setq count (1+ count))
        (let* ((key (match-string 1))
               (value (match-string 2)))
          (tds-ai-debug "Found legacy tag %d: %s[%s]" count key value)
          (tds-ai-context-store-add "LEGACY" key value)))
      (tds-ai-debug "Processed %d legacy tags total" count))))

;; airesponse block handling
(defun tds-ai-context-airesponse-disabled-p (param)
  "Check if airesponse is disabled based on PARAM.
Returns t if the parameter indicates it's disabled."
  (let ((disabled (and param (string= param "off"))))
    (tds-ai-debug "Checking if airesponse is disabled: %s -> %s"
                        (or param "nil") (if disabled "yes" "no"))
    disabled))

(defun tds-ai-context-handle-airesponse-block (start end)
  "Process airesponse block starting at START within END boundary.
Returns a cons cell (new-point . content) where:
- new-point is where to continue processing
- content is the block content if enabled, or nil if disabled."
  (tds-ai-debug "Handling airesponse block at %s (end boundary: %s)" start end)
  (save-excursion
    (goto-char start)
    (when (looking-at tds-ai-context-airesponse-regex)
      (let* ((param (match-string 2))
             (disabled (tds-ai-context-airesponse-disabled-p param))
             (block-start (match-end 0))
             (block-end nil)
             (content nil))

        (tds-ai-debug "Block starts at %s, disabled: %s" block-start disabled)

        ;; Find end of block
        (if (search-forward tds-ai-context-airesponse-end end t)
            (setq block-end (match-beginning 0))
          (setq block-end end))

        (tds-ai-debug "Block ends at %s" block-end)

        ;; Extract content if enabled
        (unless disabled
          (setq content (tds-ai-context-extract-section-content
                         block-start block-end))
          (tds-ai-debug "Extracted content: %d chars" (length content)))

        ;; Return position after block and content (or nil if disabled)
        (let ((new-point (min end (match-end 0))))
          (tds-ai-debug "Returning new point: %s, content: %s"
                              new-point (if content "yes" "nil"))
          (cons new-point content))))))

(defun tds-ai-context-extract-section-content (start end)
  "Extract content between START and END, accounting for line endings."
  (tds-ai-debug "Extracting section content from %s to %s" start end)
  (save-excursion
    (let ((content (buffer-substring-no-properties
                   (progn
                     (goto-char start)
                     (forward-line 1)
                     (point))
                   end)))
      (tds-ai-debug "Extracted %d chars" (length content))
      content)))

;; Content extraction functions
(defun tds-ai-context-extract-visible-content (start end)
  "Extract visible content from region between START and END.
Filters out comment lines and disabled airesponse blocks."
  (tds-ai-debug "Extracting visible content from %s to %s" start end)
  (let ((content "")
        (point start))

    (save-excursion
      (goto-char point)
      (while (< point end)
        (cond
         ;; Skip comment lines
         ((looking-at tds-ai-context-comment-regex)
          (tds-ai-debug "Skipping comment line at %s" point)
          (forward-line 1)
          (setq point (point)))

         ;; Handle airesponse blocks
         ((looking-at tds-ai-context-airesponse-regex)
          (tds-ai-debug "Found airesponse block at %s" point)
          (let* ((result (tds-ai-context-handle-airesponse-block point end))
                 (new-point (car result))
                 (block-content (cdr result)))

            ;; Add content if block was enabled
            (when block-content
              (tds-ai-debug "Adding enabled block content: %d chars" (length block-content))
              (setq content (concat content block-content "\n")))

            ;; Move to position after block
            (goto-char new-point)
            (setq point new-point)))

         ;; Regular content - keep it
         (t
          (let ((line-end (line-end-position)))
            (let ((line-content (buffer-substring-no-properties point line-end)))
              (tds-ai-debug "Adding regular line: %d chars" (length line-content))
              (setq content (concat content line-content "\n"))))
          (forward-line 1)
          (setq point (point))))))

    ;; Return trimmed content
    (let ((trimmed (string-trim content)))
      (tds-ai-debug "Final extracted content: %d chars" (length trimmed))
      trimmed)))

(defun tds-ai-context-get-previous-content (prompt-start max-chars)
  "Get visible content before PROMPT-START, up to MAX-CHARS characters."
  (tds-ai-debug "Getting previous content before %s (max %d chars)"
                      prompt-start max-chars)
  (let* ((start (max (point-min) (- prompt-start max-chars)))
         (content (tds-ai-context-extract-visible-content start prompt-start)))
    (tds-ai-debug "Got %d chars of previous content" (length content))

    ;; If we had to truncate, trim to the beginning of a line
    (if (> (- prompt-start start) max-chars)
        (progn
          (tds-ai-debug "Need to trim for clean start")
          (tds-ai-context-trim-to-line-start content))
      content)))

(defun tds-ai-context-get-following-content (prompt-end max-chars)
  "Get visible content after PROMPT-END, up to MAX-CHARS characters."
  (tds-ai-debug "Getting following content after %s (max %d chars)"
                      prompt-end max-chars)
  (let* ((end (min (point-max) (+ prompt-end max-chars)))
         (content (tds-ai-context-extract-visible-content prompt-end end)))
    (tds-ai-debug "Got %d chars of following content" (length content))

    ;; If we had to truncate, trim to the end of a line
    (if (> (- end prompt-end) max-chars)
        (progn
          (tds-ai-debug "Need to trim for clean end")
          (tds-ai-context-trim-to-line-end content))
      content)))

(defun tds-ai-context-trim-to-line-start (content)
  "Trim CONTENT to start at a line boundary."
  (tds-ai-debug "Trimming content to line start, original: %d chars" (length content))
  (if (string-match "\n" content)
      (let ((trimmed (substring content (match-end 0))))
        (tds-ai-debug "Trimmed to %d chars" (length trimmed))
        trimmed)
    (progn
      (tds-ai-debug "No newline found, returning as is")
      content)))

(defun tds-ai-context-trim-to-line-end (content)
  "Trim CONTENT to end at a line boundary."
  (tds-ai-debug "Trimming content to line end, original: %d chars" (length content))
  (if (string-match "\n[^\n]*$" content)
      (let ((trimmed (substring content 0 (match-beginning 0))))
        (tds-ai-debug "Trimmed to %d chars" (length trimmed))
        trimmed)
    (progn
      (tds-ai-debug "No trailing newline found, returning as is")
      content)))

;; Main context extraction function
(defun tds-ai-context-get-context (prompt-point)
  "Get context information for AI prompt at PROMPT-POINT."
  (tds-ai-debug "Getting context for prompt at %s" prompt-point)

  ;; Reset context store
  (tds-ai-context-reset-store)

  ;; Collect context from beginning of file to prompt
  (tds-ai-debug "Collecting directives from beginning of file to prompt")
  (tds-ai-context-collect-tags (point-min) prompt-point)

  ;; Collect legacy tags for backward compatibility
  (tds-ai-debug "Collecting legacy tags for backward compatibility")
  (tds-ai-context-collect-legacy-tags (point-min) prompt-point)

  ;; Get surrounding narrative context
  (tds-ai-debug "Getting surrounding narrative context")
  (let ((previous-content (tds-ai-context-get-previous-content
                           prompt-point
                           tds-ai-context-max-narrative-tokens))
        (following-content (tds-ai-context-get-following-content
                            prompt-point
                            tds-ai-context-max-narrative-tokens)))

    ;; Return context information
    (tds-ai-debug "Context collection complete, returning results")
    (list
     :store tds-ai-context-store
     :previous-content previous-content
     :following-content following-content)))

(provide 'tds-v3-ai-author-context)
;;; tds-v3-ai-author-context.el ends here
