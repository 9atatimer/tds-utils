;;; tds-ai-author-context.el --- Context enhancement for AI prompts -*- lexical-binding: t; -*-

;;; Commentary:
;; Enhances AI prompts with context from buffer comments
;; Works alongside tds-ai-author.el

;;; Code:
(require 'gptel)

;; Constants for context types
(defconst tds-context-types '("CHARACTER" "SETTING" "PLOT" "REQUEST")
  "List of recognized context types.")

;; Constants for delimiters
(defconst tds-context-prefix "% "
  "Prefix for context comments.")

(defconst tds-context-begin-marker "["
  "Beginning marker for context blocks.")

(defconst tds-context-end-marker "]"
  "Ending marker for context blocks.")

;; Template for prompts
(defcustom tds-prompt-template
  "From this CONTEXT for the scene:
{{SETTING}}
{{CHARACTER}}
{{PLOT}}
Fulfill this WRITING {{REQUEST}}
{{PROMPT}}"
  "Template for AI prompts. Use {{FIELD}} for expansion points."
  :type 'string
  :group 'tds-ai-author)

;; Helper functions
(defun tds-extract-context-by-type (type)
  "Extract context of TYPE from current buffer.
Returns a list of context strings."
  (message "Extracting %s context..." type)
  (let ((context-list '())
        (regex (concat "^" (regexp-quote tds-context-prefix)
                      (regexp-quote type)
                      (regexp-quote tds-context-begin-marker)
                      "\\(\\(.\\|\n\\)*?\\)"
                      (regexp-quote tds-context-end-marker))))
    (save-excursion
      (goto-char (point-min))
      (while (re-search-forward regex nil t)
        (let ((context-text (match-string 1)))
          (when (and context-text (not (string-empty-p context-text)))
            (push context-text context-list)
            (message "Found %s context: %s" type (substring context-text 0 (min 30 (length context-text))))))))
    (nreverse context-list)))

(defun tds-format-context-section (type contexts)
  "Format CONTEXTS of TYPE into a section.
Returns a formatted string or empty string if CONTEXTS is empty."
  (if (null contexts)
      ""
    (concat type ":\n"
            (mapconcat (lambda (ctx) (concat "* " ctx)) contexts "\n")
            "\n")))

(defun tds-collect-all-context ()
  "Collect all context from the current buffer.
Returns an alist with context type as key and formatted string as value."
  (message "Collecting all context...")
  (let ((context-data '()))
    ;; Process each context type
    (dolist (type tds-context-types)
      (let* ((contexts (tds-extract-context-by-type type))
             (formatted (when contexts
                         (tds-format-context-section type contexts))))
        (when (and formatted (not (string-empty-p formatted)))
          (push (cons type formatted) context-data))))

    (message "Collected context for %d types" (length context-data))
    context-data))

(defun tds-validate-template (template)
  "Validate that TEMPLATE placeholders are all recognized.
Throws an error if any placeholder isn't in our known types list."
  (message "Validating template...")
  (let ((known-types (append '("CHARACTERS" "PROMPT") tds-context-types))
        (invalid-placeholders '()))
    ;; Find all {{PLACEHOLDER}} patterns
    (with-temp-buffer
      (insert template)
      (goto-char (point-min))
      (while (re-search-forward "{{\\([^}]+\\)}}" nil t)
        (let ((placeholder (match-string 1)))
          ;; Check if placeholder is known
          (unless (member placeholder known-types)
            (push placeholder invalid-placeholders)))))

    ;; Throw error if any placeholders are invalid
    (when invalid-placeholders
      (user-error "Template contains unrecognized placeholders: %s"
                 (mapconcat #'identity invalid-placeholders ", ")))))

(defun tds-apply-template (template context-data prompt)
  "Apply TEMPLATE using CONTEXT-DATA and PROMPT.
Returns the filled template as a string."
  (message "Applying template...")
  ;; Validate template first
  (tds-validate-template template)

  (let ((result template))
    ;; Replace CHARACTER with CHARACTERS for plural form compatibility
    (let* ((character-content (or (cdr (assoc "CHARACTER" context-data)) "")))
      (when (not (string-empty-p character-content))
        (setq result (replace-regexp-in-string "{{CHARACTERS}}" character-content result t))))

    ;; Replace each context type placeholder
    (dolist (type tds-context-types)
      (let* ((placeholder (concat "{{" type "}}"))
             (content (or (cdr (assoc type context-data)) "")))
        (setq result (replace-regexp-in-string placeholder content result t))))

    ;; Replace prompt placeholder
    (setq result (replace-regexp-in-string "{{PROMPT}}" prompt result t))

    ;; Clean up empty sections
    (setq result (replace-regexp-in-string "\n\n\n+" "\n\n" result t))

    (message "Template applied, resulting in %d chars" (length result))
    result))

;; Debug function
(defun tds-debug-log-prompt (prompt)
  "Log full prompt to a debug buffer."
  (with-current-buffer (get-buffer-create "*AI Prompt Debug*")
    (goto-char (point-max))
    (insert "\n\n=== NEW PROMPT ===\n" prompt)
    (display-buffer (current-buffer))))

;; Functions for handling multiple versions
(defun tds-parse-prompt-version (prompt)
  "Parse PROMPT for version prefix like 'N:'.
Returns cons cell (count . actual-prompt) where count is the number
of versions requested (nil if none) and actual-prompt is the prompt
without the version prefix."
  (if (string-match "^\\([0-9]+\\):\\(.*\\)" prompt)
      (cons (string-to-number (match-string 1 prompt))
            (match-string 2 prompt))
    (cons nil prompt)))

(defun tds-insert-airesponse-after-point (point response)
  "Insert a new airesponse block after POINT with RESPONSE content."
  (save-excursion
    (goto-char point)
    (insert "\n\\begin{airesponse}\n"
            response
            "\n\\end{airesponse}\n")))

(defun tds-insert-airesponse-in-buffer (buffer insertion-point response)
  "Insert response in BUFFER at INSERTION-POINT with RESPONSE content.
Returns the new position after insertion or nil if buffer doesn't exist."
  (when (and buffer (buffer-live-p buffer))
    (with-current-buffer buffer
      (save-excursion
        (goto-char insertion-point)
        (insert "\n\\begin{airesponse}\n" response "\n\\end{airesponse}\n")
        (point)))))

;; Multi-version handler
(defun tds-handle-multi-version-response (response info)
  "Handle response for multi-version requests.
RESPONSE is the text from the AI.
INFO is a plist containing additional information."
  (let* ((data (plist-get (plist-get info :context) :data))
         (insertion-point (plist-get data :insertion-point))
         (buffer (plist-get data :buffer))
         (prompt (plist-get data :prompt))
         (current-version (plist-get data :current-version))
         (total-versions (plist-get data :total-versions))
         (enhanced-prompt (plist-get data :enhanced-prompt))
         (new-insertion-point nil))

    (message "Received version %d of %d" current-version total-versions)

    ;; Use our helper function to insert the response
    (setq new-insertion-point
          (tds-insert-airesponse-in-buffer buffer insertion-point response))

    ;; If insertion was successful, generate next version if needed
    (if new-insertion-point
        (when (< current-version total-versions)
          (message "Generating version %d of %d..."
                  (1+ current-version) total-versions)
          ;; Use the stored enhanced prompt instead of regenerating
          (let ((next-data (list :insertion-point new-insertion-point
                                :buffer buffer
                                :prompt prompt
                                :current-version (1+ current-version)
                                :total-versions total-versions
                                :enhanced-prompt enhanced-prompt)))
            (gptel-request
             enhanced-prompt
             :callback 'tds-handle-multi-version-response
             :context (list :data next-data))))
      (message "Buffer no longer exists. Cannot insert response for version %d." current-version))))

(defun tds-build-enhanced-prompt (original-prompt)
  "Build enhanced prompt by adding context to ORIGINAL-PROMPT.
Returns the enhanced prompt string."
  (message "Building enhanced prompt...")
  (let* ((context-data (tds-collect-all-context))
         (enhanced-prompt (tds-apply-template tds-prompt-template
                                             context-data
                                             original-prompt)))

    (message "Enhanced prompt built (%d chars total)" (length enhanced-prompt))
    enhanced-prompt))

;; Main function
(defun tds-process-ai-prompt-with-context ()
  "Process AI prompt with added context.
Uses the same prompt discovery as tds-process-ai-prompt but enhances
the prompt with context before sending to gptel. Supports multiple versions
with 'N:' prefix."
  (interactive)
  (message "Processing AI prompt with context...")

  ;; Reuse the existing bracket finding code from tds-ai-author
  (let ((bounds (tds-get-bracketed-text)))
    (if (not bounds)
        (message "No bracketed prompt found")

      (message "Found bracketed text: %s to %s" (car bounds) (cdr bounds))
      ;; Sanity check that it is prefixed with a latex comment
      (save-excursion
        (goto-char (car bounds))
        (backward-char (length tds-prompt-latex-prefix))
        (unless (looking-at (regexp-quote tds-prompt-latex-prefix))
          (user-error "Bracketed text not properly prefixed with '%s'" tds-prompt-latex-prefix)))

      ;; Extract the original prompt
      (let* ((start (car bounds))
             (end (cdr bounds))
             (raw-prompt (buffer-substring-no-properties (1+ start) (1- end)))
             ;; Check for version prefix
             (version-data (tds-parse-prompt-version raw-prompt))
             (version-count (car version-data))
             (actual-prompt (cdr version-data))
             ;; Generate enhanced prompt once for all versions
             (enhanced-prompt (tds-build-enhanced-prompt actual-prompt)))

        (message "Original prompt: %s"
                 (substring actual-prompt 0 (min 30 (length actual-prompt))))

        ;; Check prompt length
        (if (> (length enhanced-prompt) 4000)
            (message "Enhanced prompt too long (%d chars). Truncating may affect quality."
                     (length enhanced-prompt))
          (message "Enhanced prompt length: %d chars" (length enhanced-prompt)))

        ;; Log the prompt for debugging
        (tds-debug-log-prompt enhanced-prompt)

        ;; Handle based on whether versioning is requested
        (if version-count
            (progn
              (message "Generating %d versions..." version-count)
              ;; Start with version 1, passing the enhanced prompt
              (let ((data (list :insertion-point end
                                :buffer (current-buffer)
                                :prompt actual-prompt
                                :current-version 1
                                :total-versions version-count
                                :enhanced-prompt enhanced-prompt)))
                (gptel-request
                 enhanced-prompt
                 :callback 'tds-handle-multi-version-response
                 :context (list :data data))))

          ;; No versioning, use standard response handling
          (let ((extra-context (list :insertion-point end
                                    :prompt actual-prompt)))
            (message "Sending enhanced prompt to gptel...")
            (gptel-request
             enhanced-prompt
             :callback 'tds-handle-gptel-response
             :context extra-context)))))))

;; Function to insert context template
(defun tds-insert-context-template ()
  "Insert a context template at point."
  (interactive)
  (let* ((type (completing-read "Context type: " tds-context-types nil t))
         (template (concat tds-context-prefix type tds-context-begin-marker
                          "\n" tds-context-end-marker)))
    (insert template)
    (forward-line -1)
    (end-of-line)))

;; Function to edit the prompt template
(defun tds-edit-prompt-template ()
  "Edit the prompt template in a buffer."
  (interactive)
  (let ((buffer (get-buffer-create "*AI Prompt Template*")))
    (with-current-buffer buffer
      (erase-buffer)
      (insert ";; Edit your AI prompt template below.\n")
      (insert ";; Available placeholders: {{SETTING}}, {{CHARACTERS}}, {{PLOT}}, {{REQUEST}}, {{PROMPT}}\n\n")
      (insert "(setq tds-prompt-template \n\"")
      (insert tds-prompt-template)
      (insert "\")")
      (lisp-interaction-mode)
      (goto-char (point-max)))
    (switch-to-buffer buffer)
    (message "Edit the template and evaluate with C-j to update tds-prompt-template")))

(provide 'tds-ai-author-context-template)
;;; tds-ai-author-context.el ends here
