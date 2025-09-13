;;; tds-v3-ai-author-prompt.el --- Prompt assembly for AI author prompts -*- lexical-binding: t; -*-

;;; Commentary:
;; This file handles the assembly of prompts for AI generation,
;; taking context from document and notes to create effective prompts.
;;
;; IN SCOPE:
;; - Formatting context store data for inclusion in prompts
;; - Template expansion (handling {{KEY}} references)
;; - Assembling the complete prompt from components
;; - Constants related to prompt templates and formats
;;
;; OUT OF SCOPE:
;; - Context extraction from documents (handled by tds-v3-ai-author-context)
;; - Notes file parsing (handled by tds-v3-ai-author-notes)
;; - User-facing commands (handled by tds-v3-ai-author)
;; - LLM interaction
;; - Any LaTeX processing or file modification

;;; Code:

(require 'cl-lib)

;; Constants for prompt templates and sections
(defconst tds-ai-prompt-previous-content-section "PREVIOUS CONTENT:\n%s\n\n"
  "Format string for previous content section of the prompt.")

(defconst tds-ai-prompt-following-content-section "FOLLOWING CONTENT:\n%s\n\n"
  "Format string for following content section of the prompt.")

(defconst tds-ai-prompt-context-section "CONTEXT:\n%s\n\n"
  "Format string for context section of the prompt.")

(defconst tds-ai-prompt-main-prompt-section "PROMPT:\n%s\n\n"
  "Format string for the main prompt section.")

(defconst tds-ai-prompt-instructions
  "You are helping to write a fiction story. Follow these instructions carefully:

%s%s%sPROMPT:
%s

Generate text that fits naturally with the previous content (if any) and following content (if any).
Make sure your response fits the context and addresses the specific prompt.
"
  "Template for generating AI prompts.
Format with previous-content, following-content, context, and prompt-text.")

(defconst tds-ai-prompt-template-var-regex "{{\\([^}]+\\)}}"
  "Regular expression to match template variables in the format {{KEY}}.")

;; Configuration options
(defgroup tds-ai-prompt nil
  "Customization group for TDS AI Author Prompts."
  :group 'tools)

;; Prompt formatting functions
(defun tds-ai-prompt-format-value-list (values)
  "Format a list of VALUES as a string, with double newline separation."
  (tds-ai-debug "Formatting value list with %d items" (length values))
  (let ((result (mapconcat 'identity values "\n\n")))
    (tds-ai-debug "Formatted to %d chars" (length result))
    result))

(defun tds-ai-prompt-format-store (store)
  "Format the context STORE for inclusion in the prompt."
  (tds-ai-debug "Formatting context store")
  (let ((result "")
        (key-count 0))
    (maphash (lambda (key values)
               (when values
                 (setq key-count (1+ key-count))
                 (tds-ai-debug "Formatting key %d: %s (%d values)" 
                                     key-count key (length values))
                 (setq result 
                       (concat result 
                               (upcase key) ":\n"
                               (tds-ai-prompt-format-value-list values)
                               "\n\n"))))
             store)
    (tds-ai-debug "Formatted %d keys into %d chars total" key-count (length result))
    result))

(defun tds-ai-prompt-format-missing-var-error (var)
  "Format error message for missing variable VAR."
  (let ((msg (format "Missing value for {{%s}}" var)))
    (tds-ai-debug "%s" msg)
    msg))

(defun tds-ai-prompt-format-empty-var-error (var)
  "Format error message for empty variable VAR."
  (let ((msg (format "Empty expansion for {{%s}}" var)))
    (tds-ai-debug "%s" msg)
    msg))

;; Template expansion functions
(defun tds-ai-prompt-find-template-vars (template)
  "Find all {{KEY}} template variables in TEMPLATE.
Returns a list of matched variable names."
  (tds-ai-debug "Finding template variables in text (%d chars)" (length template))
  (let ((vars '())
        (start 0))
    (while (string-match tds-ai-prompt-template-var-regex template start)
      (let ((var (match-string 1 template)))
        (tds-ai-debug "Found variable: %s" var)
        (push var vars))
      (setq start (match-end 0)))
    (let ((result (nreverse vars)))
      (tds-ai-debug "Found %d total variables" (length result))
      result)))

(defun tds-ai-prompt-replace-var (template var replacement)
  "Replace {{VAR}} in TEMPLATE with REPLACEMENT."
  (tds-ai-debug "Replacing {{%s}} with text (%d chars)" var (length replacement))
  (let ((pattern (format "{{%s}}" var)))
    (replace-regexp-in-string pattern replacement template t t)))

(defun tds-ai-prompt-expand-template (template store)
  "Expand {{KEY}} references in TEMPLATE using the context STORE."
  (tds-ai-debug "Expanding template (%d chars)" (length template))
  (let ((case-fold-search nil)
        (result template)
        (vars (tds-ai-prompt-find-template-vars template)))
    
    ;; Check if all variables have values
    (dolist (var vars)
      (let ((values (gethash var store)))
        (tds-ai-debug "Processing variable %s: %s" 
                            var 
                            (if values 
                                (format "%d values" (length values))
                                "nil"))
        (cond
         ((not values)
          (error (tds-ai-prompt-format-missing-var-error var)))
         
         ((and (listp values) (null values))
          (error (tds-ai-prompt-format-empty-var-error var)))
         
         (t
          (let ((replacement (tds-ai-prompt-format-value-list values)))
            (tds-ai-debug "Replacing {{%s}} with %d chars" var (length replacement))
            (setq result (tds-ai-prompt-replace-var result var replacement)))))))
    
    (tds-ai-debug "Template expansion complete, result: %d chars" (length result))
    result))

;; Main prompt assembly function
(defun tds-ai-prompt-assemble (context prompt-text)
  "Assemble a complete prompt from CONTEXT and PROMPT-TEXT.
CONTEXT is a plist with :store, :previous-content, and :following-content keys."
  (tds-ai-debug "Assembling prompt")
  (let* ((store (plist-get context :store))
         (previous-content (plist-get context :previous-content))
         (following-content (plist-get context :following-content))
         (formatted-store (tds-ai-prompt-format-store store))
         (previous-section "")
         (following-section "")
         (context-section ""))
    
    ;; Format previous content section if present
    (unless (string-empty-p previous-content)
      (tds-ai-debug "Formatting previous content (%d chars)" (length previous-content))
      (setq previous-section 
            (format tds-ai-prompt-previous-content-section previous-content)))
    
    ;; Format following content section if present
    (unless (string-empty-p following-content)
      (tds-ai-debug "Formatting following content (%d chars)" (length following-content))
      (setq following-section 
            (format tds-ai-prompt-following-content-section following-content)))
    
    ;; Format context section if present
    (unless (string-empty-p formatted-store)
      (tds-ai-debug "Formatting context section (%d chars)" (length formatted-store))
      (setq context-section 
            (format tds-ai-prompt-context-section formatted-store)))
    
    ;; Try to expand template references in prompt-text
    (tds-ai-debug "Expanding template references in prompt: %s" prompt-text)
    (condition-case err
        (setq prompt-text (tds-ai-prompt-expand-template prompt-text store))
      (error
       (let ((err-msg (error-message-string err)))
         (tds-ai-debug "Template expansion error: %s" err-msg)
         (message "Warning: %s" err-msg))))
    
    ;; Format the complete prompt
    (tds-ai-debug "Formatting complete prompt")
    (let ((final-prompt (format tds-ai-prompt-instructions
                              previous-section
                              following-section
                              context-section
                              prompt-text)))
      (tds-ai-debug "Final prompt assembled: %d chars" (length final-prompt))
      final-prompt)))

(provide 'tds-v3-ai-author-prompt)
;;; tds-v3-ai-author-prompt.el ends here
