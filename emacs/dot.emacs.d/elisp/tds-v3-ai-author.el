;;; tds-v3-ai-author.el --- Main controller for AI-assisted fiction writing -*- lexical-binding: t; -*-

;;; Commentary:
;; This file serves as the main entry point and controller for the AI-assisted fiction writing system.
;;
;; IN SCOPE:
;; - User-facing interactive commands
;; - Handling file modifications (inserting/updating airesponse sections)
;; - Communicating with the LLM via gptel
;; - Coordinating the overall process flow
;; - Managing AI[] prompt detection and parsing
;; - Constants related to AI prompt format and detection
;;
;; OUT OF SCOPE:
;; - Context extraction from documents (handled by tds-v3-ai-author-context)
;; - Notes file parsing (handled by tds-v3-ai-author-notes)
;; - Prompt assembly and formatting (handled by tds-v3-ai-author-prompt)
;; - Detailed knowledge of context tags or directive formats

;;; Code:

(require 'cl-lib)
(require 'gptel)
(require 'tds-v3-ai-author-context)
(require 'tds-v3-ai-author-prompt)

;; Constants for AI prompt detection and parsing
(defconst tds-ai-prompt-regex "AI\\[[^]]*\\]"
  "Regular expression to match AI[] prompts.")

(defconst tds-ai-prompt-base-regex "AI\\[\\(.*\\)\\]"
  "Regular expression to match AI[] prompts and extract content.")

(defconst tds-ai-version-prefix-regex "^\\([0-9]+\\):\\(.*\\)"
  "Regular expression to match version prefix in prompt content.")

;; Constants for LaTeX environments
(defconst tds-response-latex-prefix "\\begin{airesponse}"
  "LaTeX prefix for AI responses.")

(defconst tds-response-latex-suffix "\\end{airesponse}"
  "LaTeX suffix for AI responses.")

(defconst tds-response-latex-off "[off]"
  "LaTeX parameter to disable a response.")

(defconst tds-response-latex-on "[on]"
  "LaTeX parameter to explicitly enable a response.")

(defconst tds-response-regex-pattern "\\\\begin{airesponse}\\(\\[\\([^]]*\\)\\]\\)?"
  "Regular expression to match the beginning of an airesponse block with optional parameter.")

;; Debug and configuration options
(defgroup tds-ai-author nil
  "Customization group for TDS AI Author."
  :group 'tools)

(defcustom tds-ai-author-gptel-model "ollama/mistral-large"
  "GPTel model to use for AI generation."
  :type 'string
  :group 'tds-ai-author)

(defcustom tds-ai-author-max-tokens 4096
  "Maximum number of tokens to generate for each response."
  :type 'integer
  :group 'tds-ai-author)

(defcustom tds-ai-author-temperature 0.8
  "Temperature parameter for LLM generation (0.0-1.0).
Higher values make output more random, lower values more deterministic."
  :type 'float
  :group 'tds-ai-author)

(defcustom tds-ai-author-debug nil
  "Whether to show debug messages and save prompts to files."
  :type 'boolean
  :group 'tds-ai-author)

(defcustom tds-ai-author-debug-file "/tmp/tds-ai-debug-prompt.txt"
  "File to save debug prompts to."
  :type 'string
  :group 'tds-ai-author)

;; Debug message function
(defun tds-ai-debug (format-string &rest args)
  "Output debug message when debug is enabled.
FORMAT-STRING and ARGS are passed to `message'."
  (when tds-ai-author-debug
    (apply #'message (concat "[TDS-AI-DEBUG] " format-string) args)))

;; Helper functions for prompt detection and parsing
(defun tds-ai-author-find-ai-prompt-at-point ()
  "Find AI[] prompt at or before point.
Returns the AI prompt as a string or nil if not found."
  (tds-ai-debug "Searching for AI prompt at current point: %s" (point))
  (save-excursion
    (let ((line-start (line-beginning-position))
          (line-end (line-end-position))
          (prompt nil))
      (goto-char line-start)
      (tds-ai-debug "Searching line from %s to %s" line-start line-end)
      (when (re-search-forward tds-ai-prompt-regex line-end t)
        (setq prompt (match-string 0))
        (tds-ai-debug "Found AI prompt: %s" prompt))
      prompt)))

(defun tds-ai-author-find-all-ai-prompts (start end)
  "Find all AI[] prompts in region between START and END.
Returns a list of (position . prompt-string) for each prompt."
  (tds-ai-debug "Finding all AI prompts between %s and %s" start end)
  (save-excursion
    (let ((prompts '()))
      (goto-char start)
      (while (re-search-forward tds-ai-prompt-regex end t)
        (let ((prompt-pos (match-beginning 0))
              (prompt-string (match-string 0)))
          (tds-ai-debug "Found AI prompt at %s: %s" prompt-pos prompt-string)
          (push (cons prompt-pos prompt-string) prompts)))
      (tds-ai-debug "Found %d AI prompts total" (length prompts))
      (nreverse prompts))))

(defun tds-ai-author-extract-prompt-content (prompt)
  "Extract content from AI[...] prompt.
Returns the content between brackets or nil if not a valid AI prompt."
  (tds-ai-debug "Extracting content from prompt: %s" prompt)
  (if (string-match tds-ai-prompt-base-regex prompt)
      (let ((content (match-string 1 prompt)))
        (tds-ai-debug "Extracted prompt content: %s" content)
        content)
    (progn
      (tds-ai-debug "Not a valid AI prompt format: %s" prompt)
      nil)))

(defun tds-ai-author-parse-prompt-content (content)
  "Parse prompt CONTENT for optional version prefix.
Returns plist with :count, :prompt, and :is-duplex keys."
  (tds-ai-debug "Parsing prompt content: %s" content)
  (if (string-match tds-ai-version-prefix-regex content)
      (let* ((count (string-to-number (match-string 1 content)))
             (prompt (string-trim (match-string 2 content))))
        (tds-ai-debug "Found explicit version prefix - count: %d, prompt: %s" count prompt)
        (list :count count :prompt prompt :is-duplex t))
    ;; No version prefix, entire content is the prompt
    (let ((prompt (string-trim content)))
      (tds-ai-debug "No version prefix - count: 1, prompt: %s, duplex: nil" prompt)
      (list :count 1 :prompt prompt :is-duplex nil))))

(defun tds-ai-author-parse-ai-prompt (prompt)
  "Parse an AI[] prompt string.
Returns plist with :count, :prompt, and :is-duplex keys."
  (let ((content (tds-ai-author-extract-prompt-content prompt)))
    (if content
        (tds-ai-author-parse-prompt-content content)
      nil)))

;; Functions for managing airesponse blocks
(defun tds-ai-author-find-existing-airesponses (start end)
  "Find all airesponse blocks in region between START and END.
Returns a list of (begin . end) positions for each block."
  (tds-ai-debug "Finding airesponse blocks between %s and %s" start end)
  (save-excursion
    (let ((blocks '()))
      (goto-char start)
      (while (re-search-forward tds-response-latex-prefix end t)
        (let ((begin (match-beginning 0)))
          (tds-ai-debug "Found airesponse start at %s" begin)
          (when (re-search-forward tds-response-latex-suffix end t)
            (let ((end-pos (match-end 0)))
              (tds-ai-debug "Found matching end at %s" end-pos)
              (push (cons begin end-pos) blocks)))))
      (tds-ai-debug "Found %d airesponse blocks total" (length blocks))
      (nreverse blocks))))

(defun tds-ai-author-find-immediate-response (position)
  "Find airesponse block immediately following POSITION.
Returns (begin . end) if found, nil otherwise.
Only finds response that starts right after POSITION (allowing whitespace)."
  (tds-ai-debug "Looking for immediate response after %s" position)
  (save-excursion
    (goto-char position)
    ;; Skip whitespace but nothing else
    (skip-chars-forward " \t\n\r")
    ;; Check if we're looking at an airesponse start
    (if (looking-at (regexp-quote tds-response-latex-prefix))
        (let ((begin (match-beginning 0)))
          ;; Find the matching end
          (if (re-search-forward (regexp-quote tds-response-latex-suffix) nil t)
              (let ((end (match-end 0)))
                (tds-ai-debug "Found immediate response from %s to %s" begin end)
                (cons begin end))
            (progn
              (tds-ai-debug "Found response start but no matching end")
              nil)))
      (progn
        (tds-ai-debug "No immediate response found")
        nil))))

(defun tds-ai-author-clear-airesponses (start end)
  "Remove all airesponse blocks between START and END."
  (tds-ai-debug "Clearing airesponse blocks between %s and %s" start end)
  (save-excursion
    (let ((blocks (tds-ai-author-find-existing-airesponses start end)))
      (dolist (block blocks)
        (tds-ai-debug "Deleting block from %s to %s" (car block) (cdr block))
        (delete-region (car block) (cdr block)))
      (tds-ai-debug "Cleared %d airesponse blocks" (length blocks)))))

(defun tds-ai-author-find-airesponse-at-point ()
  "Find airesponse environment at point.
Returns a list (begin . end) or nil if not found."
  (tds-ai-debug "Searching for airesponse at current point: %s" (point))
  (save-excursion
    (let ((line-start (line-beginning-position)))
      (goto-char line-start)
      (if (re-search-forward tds-response-regex-pattern (line-end-position) t)
          (let ((begin (match-beginning 0))
                (end (match-end 0)))
            (tds-ai-debug "Found airesponse at current line: %s to %s" begin end)
            (cons begin end))
        (progn
          (tds-ai-debug "Not found on current line, searching backward")
          (when (re-search-backward tds-response-regex-pattern nil t)
            (let ((begin (match-beginning 0))
                  (end (match-end 0)))
              (tds-ai-debug "Found airesponse in backward search: %s to %s" begin end)
              (cons begin end))))))))

;; LLM interaction functions
(defun tds-ai-author-handle-gptel-response (response info)
  "Handle the response from gptel.
RESPONSE is the text from the AI.
INFO is a plist containing additional information."
  (let* ((context-data (plist-get info :context))
         (buffer (plist-get context-data :buffer))
         (insertion-point (plist-get context-data :insertion-point))
         (prompt (plist-get context-data :prompt))
         (enhanced-prompt (plist-get context-data :enhanced-prompt))
         (count (plist-get context-data :count))
         (is-duplex (plist-get context-data :is-duplex))
         (current-version (or (plist-get context-data :current-version) 1))
         (timestamp (format-time-string "%Y-%m-%d %H:%M:%S"))
         (model-name (or gptel-model tds-ai-author-gptel-model "unknown")))

    (tds-ai-debug "Received response for version %d of %d" current-version count)

    ;; Check if buffer still exists
    (if (not (buffer-live-p buffer))
        (progn
          (tds-ai-debug "Buffer no longer exists, aborting")
          (message "Buffer closed, stopping generation at version %d of %d"
                   current-version count))

      ;; Insert this response
      (let ((new-insertion-point
             (with-current-buffer buffer
               (save-excursion
                 (goto-char insertion-point)

                 ;; For non-duplex single responses only, clear any existing response
                 (when (and (= count 1) (= current-version 1) (not is-duplex))
                   (let ((existing (tds-ai-author-find-immediate-response insertion-point)))
                     (when existing
                       (tds-ai-debug "Clearing existing single response from %s to %s"
                                    (car existing) (cdr existing))
                       (delete-region (car existing) (cdr existing))
                       ;; After deletion, we're at the right spot
                       (goto-char insertion-point))))

                 (let* ((metadata (if (> count 1)
                                     (format "%% Generated: %s, Model: %s [Version %d of %d]"
                                            timestamp model-name current-version count)
                                   (format "%% Generated: %s, Model: %s"
                                          timestamp model-name)))
                        (disabled (and (> count 1) (> current-version 1))))
                   (insert (format "\n%s%s\n%s\n%s\n%s\n"
                                  tds-response-latex-prefix
                                  (if disabled tds-response-latex-off "")
                                  response
                                  metadata
                                  tds-response-latex-suffix))
                   (tds-ai-debug "Inserted version %d %s"
                                current-version
                                (if disabled "(disabled)" "(enabled)"))
                   (point))))))

        ;; If more versions needed, fire next request
        (if (< current-version count)
            (progn
              (tds-ai-debug "Requesting version %d of %d" (1+ current-version) count)
              (let ((next-context (list :buffer buffer
                                       :insertion-point new-insertion-point
                                       :prompt prompt
                                       :enhanced-prompt enhanced-prompt
                                       :count count
                                       :is-duplex is-duplex
                                       :current-version (1+ current-version))))
                (gptel-request
                 enhanced-prompt
                 :callback 'tds-ai-author-handle-gptel-response
                 :context next-context))
              (message "Generating version %d of %d..." (1+ current-version) count))

          ;; All versions complete
          (message "Generated %d AI response version%s"
                   count (if (> count 1) "s" "")))))))

(defun tds-ai-author-split-response (response count)
  "Split RESPONSE into COUNT parts at paragraph boundaries."
  (tds-ai-debug "Splitting response into %d parts" count)
  (if (<= count 1)
      (progn
        (tds-ai-debug "Count <= 1, returning single response")
        (list response))
    (let* ((paragraphs (split-string response "\n\n"))
           (paragraphs-count (length paragraphs))
           (parts-size (max 1 (/ paragraphs-count count)))
           (parts '())
           (current-part '())
           (i 0))

      (tds-ai-debug "Found %d paragraphs, targeting ~%d per part"
                           paragraphs-count parts-size)

      (dolist (para paragraphs)
        (push para current-part)
        (setq i (1+ i))
        (when (or (= i paragraphs-count)
                  (and (>= (length current-part) parts-size)
                       (< (length parts) (1- count))))
          (let ((part-text (string-join (nreverse current-part) "\n\n")))
            (tds-ai-debug "Created part %d with %d paragraphs (%d chars)"
                                (1+ (length parts)) (length current-part) (length part-text))
            (push part-text parts))
          (setq current-part '())
          (setq i 0)))

      (tds-ai-debug "Created %d parts total" (length parts))
      (nreverse parts))))

;; Main processing functions
(defun tds-ai-author-process-ai-prompt (prompt-point prompt-string)
  "Process AI prompt at PROMPT-POINT with content PROMPT-STRING.
Generates response(s) and inserts them after the prompt."
  (tds-ai-debug "Processing AI prompt at %s: %s" prompt-point prompt-string)
  (let* ((parsed (tds-ai-author-parse-ai-prompt prompt-string))
         (count (plist-get parsed :count))
         (prompt-text (plist-get parsed :prompt))
         (is-duplex (plist-get parsed :is-duplex))
         (current-buffer-ref (current-buffer)))

    (tds-ai-debug "Getting context for point %s" prompt-point)
    (let ((context (tds-ai-context-get-context prompt-point)))
      (tds-ai-debug "Context retrieved, assembling prompt")
      (let ((full-prompt (tds-ai-prompt-assemble context prompt-text)))
        (tds-ai-debug "Prompt assembled (%d chars), invoking LLM" (length full-prompt))

        ;; Save debug prompt if configured
        (when tds-ai-author-debug
          (with-temp-file tds-ai-author-debug-file
            (insert full-prompt))
          (tds-ai-debug "Saved prompt to %s" tds-ai-author-debug-file))

        ;; Find insertion point (end of current line with the AI prompt)
        (save-excursion
          (goto-char prompt-point)
          (let ((insertion-point (line-end-position)))

            ;; Create context data for callback with buffer reference and enhanced prompt
            (let ((callback-context (list :buffer current-buffer-ref
                                         :insertion-point insertion-point
                                         :prompt prompt-text
                                         :enhanced-prompt full-prompt
                                         :count count
                                         :is-duplex is-duplex
                                         :current-version 1)))

              ;; Send first request to gptel with callback
              (tds-ai-debug "Sending request 1 of %d to gptel" count)
              (gptel-request
               full-prompt
               :callback 'tds-ai-author-handle-gptel-response
               :context callback-context)

              (message "Generating version 1 of %d..." count))))))))

;; Interactive commands
;;;###autoload
(defun tds-ai-author-process-prompt-at-point ()
  "Process AI prompt at point, generate response, and insert it."
  (interactive)
  (tds-ai-debug "Invoked process-prompt-at-point at %s" (point))
  (let ((prompt (tds-ai-author-find-ai-prompt-at-point)))
    (if (not prompt)
        (progn
          (tds-ai-debug "No AI prompt found at point")
          (message "No AI[] prompt found at point"))
      (tds-ai-debug "Found prompt: %s, processing" prompt)
      (tds-ai-author-process-ai-prompt (point) prompt))))

;;;###autoload
(defun tds-ai-author-process-all-prompts ()
  "Process all AI[] prompts in the current buffer."
  (interactive)
  (tds-ai-debug "Invoked process-all-prompts in buffer %s" (buffer-name))
  (let ((prompts (tds-ai-author-find-all-ai-prompts (point-min) (point-max))))
    (if (null prompts)
        (progn
          (tds-ai-debug "No AI prompts found in buffer")
          (message "No AI[] prompts found in buffer"))
      (tds-ai-debug "Processing %d prompts" (length prompts))
      (dolist (prompt prompts)
        (tds-ai-debug "Processing prompt at %s: %s" (car prompt) (cdr prompt))
        (tds-ai-author-process-ai-prompt (car prompt) (cdr prompt)))
      (message "Processed %d AI[] prompts" (length prompts)))))

;;;###autoload
(defun tds-ai-author-toggle-airesponse-status ()
  "Toggle the enabled/disabled status of the airesponse block at point."
  (interactive)
  (tds-ai-debug "Invoked toggle-airesponse-status at %s" (point))
  (let ((response-pos (tds-ai-author-find-airesponse-at-point)))
    (if (not response-pos)
        (progn
          (tds-ai-debug "No airesponse block found at or near point")
          (user-error "Not in or near an airesponse block"))

      (save-excursion
        (goto-char (car response-pos))
        (tds-ai-debug "Found airesponse at %s" (car response-pos))
        (when (looking-at tds-response-regex-pattern)
          (let ((param (match-string 2))
                (param-start (match-beginning 1))
                (param-end (match-end 1)))

            (tds-ai-debug "Current parameter: %s" (or param "none"))

            (cond
             ;; No parameter or empty parameter (enabled) -> disable
             ((or (not param) (string= param "") (string= param "on"))
              (if param-start
                  (delete-region param-start param-end)
                (goto-char (match-end 0)))
              (insert tds-response-latex-off)
              (tds-ai-debug "Disabled response")
              (message "Response disabled"))

             ;; Off parameter -> enable
             ((string= param "off")
              (delete-region param-start param-end)
              (tds-ai-debug "Enabled response")
              (message "Response enabled")))))))))

(provide 'tds-v3-ai-author)
;;; tds-v3-ai-author.el ends here
