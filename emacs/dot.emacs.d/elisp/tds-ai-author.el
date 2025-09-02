;;; tds-ai-author.el --- AI author assistance functions -*- lexical-binding: t; -*-

;;; Commentary:
;; Functions to help with AI-assisted writing for romantasy serials
;; Designed to work with gptel and Ollama

;;; Code:
(require 'gptel)

;; Constants for markers
(defconst tds-prompt-latex-prefix "% AI")
(defconst tds-prompt-begin-marker "[")
(defconst tds-prompt-end-marker "]")
(defconst tds-ai-begin-marker "\\begin{airesponse}")  ;; now using \'s and {'s
(defconst tds-ai-end-marker "\\end{airesponse}")  ;; Fixed typo (was airresponse)

;; Function to find bracketed text
(defun tds-get-bracketed-text ()
  "Find and return bracketed text near point.
Returns a cons cell (start . end) of buffer positions or nil if not found."
  (save-excursion
    (let (start end)
      ;; Go to beginning of bracket if not already there
      (when (not (looking-at (regexp-quote tds-prompt-begin-marker)))
        (search-backward tds-prompt-begin-marker nil t))
      (setq start (point))
      ;; Find closing bracket
      (when (search-forward tds-prompt-end-marker nil t)
        (setq end (point))
        ;; Return the positions
        (cons start end)))))

;; Function to find AI response regions
(defun tds-find-ai-response-region (position)
  "Find the AI response region near POSITION.
Returns a cons cell (start . end) of buffer positions or nil if not found.
Only finds response regions that follow immediately after POSITION."
  (save-excursion
    (goto-char position)
    ;; Skip whitespace after the insertion point
    (skip-chars-forward "\t\r\n ")
    (let (start end)
      ;; Check if we're looking at the BEGIN marker
      (if (looking-at (regexp-quote tds-ai-begin-marker))
          (progn
            (forward-line 1)
            (setq start (point))
            ;; Find the END marker
            (when (re-search-forward (regexp-quote tds-ai-end-marker) nil t)
              (beginning-of-line)
              (setq end (point))
              ;; Return the positions
              (cons start end)))
        ;; No BEGIN marker found at the expected position
        nil))))

;; Function to insert or update AI response
(defun tds-insert-or-update-ai-response (prompt position response)
  "Insert or update an AI response at POSITION for PROMPT with RESPONSE."
  (save-excursion
    ;; Check if there's already a response
    (goto-char position)
    (message "Checking for existing response at position %s" position)
    (let ((existing-response (tds-find-ai-response-region position)))
      (if existing-response
          (progn
            (message "Found existing response from %s to %s" (car existing-response) (cdr existing-response))
            ;; Update existing response
            (let ((start (car existing-response))
                  (end (cdr existing-response)))
              (delete-region start end)
              (goto-char start)
              ;; Ensure response always has proper newline handling
              (unless (string-suffix-p "\n" response)
                (setq response (concat response "\n")))
              (insert response)
              (message "Updated existing response")))
        (progn
          (message "No existing response found, creating new one")
          ;; Insert new response
          (goto-char position)
          (insert "\n" tds-ai-begin-marker "\n")
          (insert response)
          (insert "\n" tds-ai-end-marker "\n")
          (message "New response inserted"))))))

;; Handler function for gptel responses
(defun tds-handle-gptel-response (response info)
  "Handle the response from gptel.
RESPONSE is the text from the AI.
INFO is a plist containing additional information."
  (let ((insertion-point (plist-get (plist-get info :context) :insertion-point))
        (prompt (plist-get (plist-get info :context) :prompt)))
    (message "Received response: %s" (substring response 0 (min 30 (length response))))
    (tds-insert-or-update-ai-response prompt insertion-point response)
    (message "Response inserted successfully")))

;; Main function to expand or update AI content
(defun tds-process-ai-prompt ()
  "Process bracketed prompt to generate or update AI content."
  (interactive)
  (message "Searching for bracketed text...")
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

      ;; extract the prompt
      (let* ((start (car bounds))
             (end (cdr bounds))
             (prompt (buffer-substring-no-properties (1+ start) (1- end))))
        (message "Extracted prompt: %s" prompt)

        ;; Add length check
        (if (> (length prompt) 1000)
            (message "Prompt too long (%d chars). Keep it under 1000 chars." (length prompt))

          ;; Create the extra context
          (let ((extra-context (list :insertion-point end :prompt prompt)))
            (message "Sending to gptel with info: %S" extra-context)
            (gptel-request
             prompt
             :callback 'tds-handle-gptel-response
             :context extra-context)))))))

;; Function to edit AI responses
(defun tds-edit-ai-response ()
  "Find and edit AI response region using paste-and-ediff."
  (interactive)
  (let ((bounds (tds-find-ai-response-region)))
    (if (not bounds)
        (message "No AI response region found near point")
      (let ((start (car bounds))
            (end (cdr bounds)))
        ;; Select the region
        (goto-char start)
        (set-mark-command nil)
        (goto-char end)
        (setq deactivate-mark nil)
        ;; Call paste-and-ediff-clipboard-region from user's config
        (call-interactively 'paste-and-ediff-clipboard-region)))))

(provide 'tds-ai-author)
;;; tds-ai-author.el ends here
