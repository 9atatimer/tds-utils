;;; tds-v3-ai-author.el --- Main controller for AI-assisted fiction writing -*- lexical-binding: t; -*-

;;; Commentary:
;; This file serves as the main entry point and controller for the AI-assisted fiction writing system.
;;
;; IN SCOPE:
;; - User-facing interactive commands
;; - Handling file modifications (inserting/updating airesponse sections)
;; - Communicating with the LLM via gptel
;; - Coordinating the overall process flow
;; - Managing AI[] tag detection and parsing
;; - Constants related to AI tag format and detection
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

;; Constants for AI tag detection and parsing
(defconst tds-ai-tag-regex "AI\\[[^]]*\\]"
  "Regular expression to match AI[] tags.")

(defconst tds-ai-tag-with-number-regex "AI\\[\\([0-9]*\\):\\(.*\\)\\]"
  "Regular expression to match AI[] tags with an optional count prefix.")

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

;; Helper functions for tag detection and parsing
(defun tds-ai-author-find-ai-tag-at-point ()
  "Find AI[] tag at or before point.
Returns the AI tag as a string or nil if not found."
  (tds-ai-debug "Searching for AI tag at current point: %s" (point))
  (save-excursion
    (let ((line-start (line-beginning-position))
          (line-end (line-end-position))
          (tag nil))
      (goto-char line-start)
      (tds-ai-debug "Searching line from %s to %s" line-start line-end)
      (when (re-search-forward tds-ai-tag-regex line-end t)
        (setq tag (match-string 0))
        (tds-ai-debug "Found AI tag: %s" tag))
      tag)))

(defun tds-ai-author-find-all-ai-tags (start end)
  "Find all AI[] tags in region between START and END.
Returns a list of (position . tag-string) for each tag."
  (tds-ai-debug "Finding all AI tags between %s and %s" start end)
  (save-excursion
    (let ((tags '()))
      (goto-char start)
      (while (re-search-forward tds-ai-tag-regex end t)
        (let ((tag-pos (match-beginning 0))
              (tag-string (match-string 0)))
          (tds-ai-debug "Found AI tag at %s: %s" tag-pos tag-string)
          (push (cons tag-pos tag-string) tags)))
      (tds-ai-debug "Found %d AI tags total" (length tags))
      (nreverse tags))))

(defun tds-ai-author-parse-ai-tag (tag)
  "Parse an AI[] tag string.
Returns (count . prompt) where count is the number of responses
to generate (defaults to 1) and prompt is the prompt text."
  (tds-ai-debug "Parsing AI tag: %s" tag)
  (when (string-match tds-ai-tag-with-number-regex tag)
    (let* ((count-str (match-string 1 tag))
           (prompt (match-string 2 tag))
           (count (if (string-empty-p count-str)
                     1
                   (string-to-number count-str))))
      (tds-ai-debug "Parsed tag - count: %d, prompt: %s" count prompt)
      (cons count (string-trim prompt)))))

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
         (insertion-point (plist-get context-data :insertion-point))
         (prompt (plist-get context-data :prompt))
         (count (plist-get context-data :count)))
    (tds-ai-debug "Received response for prompt: %s"
                  (substring prompt 0 (min 30 (length prompt))))
    ;; Generate metadata comment
    (let* ((timestamp (format-time-string "%Y-%m-%d %H:%M:%S"))
           (model-name (or gptel-model tds-ai-author-gptel-model "unknown"))
           (metadata-comment (format "%% Generated: %s, Model: %s"
                                    timestamp model-name)))
      (if (= count 1)
          ;; Single response - insert with metadata
          (save-excursion
            (goto-char insertion-point)
            (insert (format "\n\n%s\n%s\n%s\n%s\n"
                           tds-response-latex-prefix
                           response
                           metadata-comment
                           tds-response-latex-suffix))
            (tds-ai-debug "Inserted single response with metadata")
            (message "Generated AI response"))
        ;; Multiple responses - split and insert
        (tds-ai-author-handle-multi-version-response response info)))))

(defun tds-ai-author-handle-multi-version-response (response info)
  "Handle multi-version response generation.
RESPONSE is the text from the AI.
INFO is a plist containing additional information."
  (let* ((context-data (plist-get info :context))
         (insertion-point (plist-get context-data :insertion-point))
         (count (plist-get context-data :count))
         (parts (tds-ai-author-split-response response count))
         (timestamp (format-time-string "%Y-%m-%d %H:%M:%S"))
         (model-name (or gptel-model tds-ai-author-gptel-model "unknown")))

    (tds-ai-debug "Handling %d versions" count)

    ;; Insert first response (enabled)
    (save-excursion
      (goto-char insertion-point)
      (let ((first-part (car parts))
            (metadata (format "%% Generated: %s, Model: %s [Version 1 of %d]"
                            timestamp model-name count)))
        (insert (format "\n\n%s\n%s\n%s\n%s\n"
                       tds-response-latex-prefix
                       first-part
                       metadata
                       tds-response-latex-suffix))
        (tds-ai-debug "Inserted version 1 (enabled)"))

      ;; Insert remaining responses (disabled)
      (let ((version-num 2))
        (dolist (part (cdr parts))
          (unless (string-empty-p (string-trim part))
            (let ((metadata (format "%% Generated: %s, Model: %s [Version %d of %d]"
                                  timestamp model-name version-num count)))
              (insert (format "\n%s%s\n%s\n%s\n%s\n"
                            tds-response-latex-prefix
                            tds-response-latex-off
                            part
                            metadata
                            tds-response-latex-suffix))
              (tds-ai-debug "Inserted version %d (disabled)" version-num)
              (setq version-num (1+ version-num))))))

    (message "Generated %d AI response versions" count))))

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
(defun tds-ai-author-process-ai-tag (tag-point tag-string)
  "Process AI tag at TAG-POINT with content TAG-STRING.
Generates response(s) and inserts them after the tag."
  (tds-ai-debug "Processing AI tag at %s: %s" tag-point tag-string)
  (let* ((parsed (tds-ai-author-parse-ai-tag tag-string))
         (count (car parsed))
         (prompt-text (cdr parsed)))

    (tds-ai-debug "Getting context for point %s" tag-point)
    (let ((context (tds-ai-context-get-context tag-point)))
      (tds-ai-debug "Context retrieved, assembling prompt")
      (let ((full-prompt (tds-ai-prompt-assemble context prompt-text)))
        (tds-ai-debug "Prompt assembled (%d chars), invoking LLM" (length full-prompt))

        ;; Save debug prompt if configured
        (when tds-ai-author-debug
          (with-temp-file tds-ai-author-debug-file
            (insert full-prompt))
          (tds-ai-debug "Saved prompt to %s" tds-ai-author-debug-file))

        ;; Find insertion point (end of current line with the AI tag)
        (save-excursion
          (goto-char tag-point)
          (let ((insertion-point (line-end-position)))

            ;; Clear any existing airesponse blocks between here and next tag
            (let ((next-tag-point (save-excursion
                                   (if (re-search-forward tds-ai-tag-regex nil t)
                                       (match-beginning 0)
                                     (point-max)))))
              (tds-ai-debug "Clearing existing responses between %s and %s"
                           insertion-point next-tag-point)
              (tds-ai-author-clear-airesponses insertion-point next-tag-point))

            ;; Create context data for callback
            (let ((callback-context (list :insertion-point insertion-point
                                         :prompt prompt-text
                                         :count count)))

              ;; Send request to gptel with callback
              (tds-ai-debug "Sending request to gptel")
              (gptel-request
               full-prompt
               :callback 'tds-ai-author-handle-gptel-response
               :context callback-context)

              (message "Sent prompt to LLM (expecting %d response%s)..."
                      count (if (> count 1) "s" "")))))))))

;; Interactive commands
;;;###autoload
(defun tds-ai-author-process-tag-at-point ()
  "Process AI tag at point, generate response, and insert it."
  (interactive)
  (tds-ai-debug "Invoked process-tag-at-point at %s" (point))
  (let ((tag (tds-ai-author-find-ai-tag-at-point)))
    (if (not tag)
        (progn
          (tds-ai-debug "No AI tag found at point")
          (message "No AI[] tag found at point"))
      (tds-ai-debug "Found tag: %s, processing" tag)
      (tds-ai-author-process-ai-tag (point) tag))))

;;;###autoload
(defun tds-ai-author-process-all-tags ()
  "Process all AI[] tags in the current buffer."
  (interactive)
  (tds-ai-debug "Invoked process-all-tags in buffer %s" (buffer-name))
  (let ((tags (tds-ai-author-find-all-ai-tags (point-min) (point-max))))
    (if (null tags)
        (progn
          (tds-ai-debug "No AI tags found in buffer")
          (message "No AI[] tags found in buffer"))
      (tds-ai-debug "Processing %d tags" (length tags))
      (dolist (tag tags)
        (tds-ai-debug "Processing tag at %s: %s" (car tag) (cdr tag))
        (tds-ai-author-process-ai-tag (car tag) (cdr tag)))
      (message "Processed %d AI[] tags" (length tags)))))

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
