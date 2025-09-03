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

;; Constants for formatting
(defconst tds-context-header "CONTEXT:\n"
  "Header for the context section in the prompt.")

(defconst tds-request-header "\nWRITING REQUEST:\n"
  "Header for the request section in the prompt.")

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
            "\n\n")))

(defun tds-collect-all-context ()
  "Collect all context from the current buffer.
Returns a cons cell (context . request) where context is the formatted
context string and request is any REQUEST context to prepend to prompts."
  (message "Collecting all context...")
  (let ((formatted-context "")
        (request-context ""))

    ;; Process each context type except REQUEST
    (dolist (type (remove "REQUEST" tds-context-types))
      (let ((contexts (tds-extract-context-by-type type)))
        (when contexts
          (setq formatted-context
                (concat formatted-context
                        (tds-format-context-section type contexts))))))

    ;; Process REQUEST separately
    (let ((requests (tds-extract-context-by-type "REQUEST")))
      (when requests
        (setq request-context (mapconcat #'identity requests "\n"))))

    (message "Collected %d chars of context and %d chars of request context"
             (length formatted-context) (length request-context))

    ;; Return as cons cell
    (cons formatted-context request-context)))

(defun tds-build-enhanced-prompt (original-prompt)
  "Build enhanced prompt by adding context to ORIGINAL-PROMPT.
Returns the enhanced prompt string."
  (message "Building enhanced prompt...")
  (let* ((context-data (tds-collect-all-context))
         (context (car context-data))
         (request (cdr context-data))
         (enhanced-prompt ""))

    ;; Add context header if we have context
    (when (not (string-empty-p context))
      (setq enhanced-prompt (concat tds-context-header context)))

    ;; Add request header
    (setq enhanced-prompt (concat enhanced-prompt tds-request-header))

    ;; Add request context if any
    (when (not (string-empty-p request))
      (setq enhanced-prompt (concat enhanced-prompt request "\n\n")))

    ;; Add original prompt
    (setq enhanced-prompt (concat enhanced-prompt original-prompt))

    (message "Enhanced prompt built (%d chars total)" (length enhanced-prompt))
    enhanced-prompt))

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

;; Multi-version handler
(defun tds-handle-multi-version-response (response info)
  "Handle response for multi-version requests.
RESPONSE is the text from the AI.
INFO is a plist containing additional information."
  (let* ((data (plist-get (plist-get info :context) :data))
         (insertion-point (plist-get data :insertion-point))
         (prompt (plist-get data :prompt))
         (current-version (plist-get data :current-version))
         (total-versions (plist-get data :total-versions)))

    (message "Received version %d of %d" current-version total-versions)

    ;; Insert this response as a new airesponse block
    (tds-insert-airesponse-after-point insertion-point response)

    ;; Update insertion point to be after this newly inserted block
    (save-excursion
      (goto-char insertion-point)
      ;; Find the end of the airesponse we just inserted
      (search-forward "\\end{airesponse}\n" nil t)
      (setq insertion-point (point)))

    ;; If we have more versions to generate, request the next one
    (when (< current-version total-versions)
      (message "Generating version %d of %d..."
               (1+ current-version) total-versions)
      (let* ((enhanced-prompt (tds-build-enhanced-prompt prompt))
             (next-data (list :insertion-point insertion-point
                             :prompt prompt
                             :current-version (1+ current-version)
                             :total-versions total-versions)))
        (gptel-request
         enhanced-prompt
         :callback 'tds-handle-multi-version-response
         :context (list :data next-data))))))

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
             (enhanced-prompt (tds-build-enhanced-prompt actual-prompt)))

        (message "Original prompt: %s"
                 (substring actual-prompt 0 (min 30 (length actual-prompt))))

        ;; Check prompt length
        (if (> (length enhanced-prompt) 4000)
            (message "Enhanced prompt too long (%d chars). Truncating may affect quality."
                     (length enhanced-prompt))
          (message "Enhanced prompt length: %d chars" (length enhanced-prompt)))

        ;; Handle based on whether versioning is requested
        (if version-count
            (progn
              (message "Generating %d versions..." version-count)
              ;; Start with version 1
              (let ((data (list :insertion-point end
                               :prompt actual-prompt
                               :current-version 1
                               :total-versions version-count)))
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

(provide 'tds-ai-author-context)
;;; tds-ai-author-context.el ends here
