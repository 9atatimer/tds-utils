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

;; Main function 
(defun tds-process-ai-prompt-with-context ()
  "Process AI prompt with added context.
Uses the same prompt discovery as tds-process-ai-prompt but enhances
the prompt with context before sending to gptel."
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
             (original-prompt (buffer-substring-no-properties (1+ start) (1- end)))
             (enhanced-prompt (tds-build-enhanced-prompt original-prompt)))
        
        (message "Original prompt: %s" 
                 (substring original-prompt 0 (min 30 (length original-prompt))))
        
        ;; Check prompt length
        (if (> (length enhanced-prompt) 4000)
            (message "Enhanced prompt too long (%d chars). Truncating may affect quality." 
                     (length enhanced-prompt))
          (message "Enhanced prompt length: %d chars" (length enhanced-prompt)))
        
        ;; Send to gptel using the existing callback mechanism
        (let ((extra-context (list :insertion-point end :prompt original-prompt)))
          (message "Sending enhanced prompt to gptel...")
          (gptel-request
           enhanced-prompt
           :callback 'tds-handle-gptel-response
           :context extra-context))))))

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
;;; tds-ai-uthor-context.el ends here
