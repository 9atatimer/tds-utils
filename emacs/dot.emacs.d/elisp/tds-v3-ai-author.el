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

;; FIXME: Legacy tag collection is too greedy - collecting AI prompts as context
;; 
;; ISSUE: The legacy tag collector (tds-ai-context-collect-legacy-tags) matches
;; any pattern of the form % KEY[...] and stores it as LEGACY:KEY context.
;; This means AI prompts (% AI[...]) are being collected and sent back to the
;; LLM as part of the context, causing contamination of responses.
;;
;; SYMPTOMS:
;; - AI prompts from earlier in the document appear in LEGACY:AI context
;; - Test prompts like "just say hello" affect all subsequent generations
;; - The LLM sees its own prompts as context, creating feedback loops
;;
;; POTENTIAL FIXES:
;; 1. Blacklist approach: Skip "AI" key when collecting legacy tags
;;    - Simple: (unless (string= key "AI") ...) 
;;    - But what about other keys we don't want?
;;
;; 2. Whitelist approach: Only collect known context keys
;;    - Define allowed keys: CHARACTER, SETTING, PLOT, etc.
;;    - Reject everything else
;;    - More maintainable but less flexible
;;
;; 3. Different prefix: Use %% for context vs % for prompts
;;    - Would break existing documents
;;    - Cleaner separation of concerns
;;
;; 4. Warning system: Log unknown keys, don't include them
;;    - Helps users debug their markup
;;    - Prevents silent contamination
;;
;; TEMPORARY WORKAROUND: Users should avoid legacy format (% KEY[...]) 
;; and use the new format (% VERB:STORE:KEY) which doesn't have this issue.
;;
;; TODO: Implement fix before this bites someone in production

;;; Code:

(require 'cl-lib)
(require 'gptel)
(require 'tds-v3-ai-author-context)
(require 'tds-v3-ai-author-prompt)

;; Constants for AI prompt detection and parsing
(defconst tds-ai-prompt-prefix "% AI"
  "Required prefix for AI prompts in LaTeX comments.")

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

(defconst tds-response-placeholder-text "[Generating response...]"
  "Placeholder text shown while waiting for LLM response.")

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

(defcustom tds-ai-author-prompt-max-length 4000
  "Maximum prompt length before warning (in characters)."
  :type 'integer
  :group 'tds-ai-author)

(defcustom tds-ai-author-prompt-danger-length 6000
  "Prompt length that triggers stronger warning (in characters)."
  :type 'integer
  :group 'tds-ai-author)

(defcustom tds-ai-author-debug t
  "Whether to show debug messages and save prompts to files."
  :type 'boolean
  :group 'tds-ai-author)

(defcustom tds-ai-author-debug-file "/tmp/tds-ai-debug-prompt.txt"
  "File to save debug prompts to."
  :type 'string
  :group 'tds-ai-author)

(defcustom tds-ai-author-debug-buffer "*AI Prompt Debug*"
  "Buffer name for debug prompt display."
  :type 'string
  :group 'tds-ai-author)

;; Debug message function
(defun tds-ai-debug (format-string &rest args)
  "Output debug message when debug is enabled.
FORMAT-STRING and ARGS are passed to `message'."
  (when tds-ai-author-debug
    (apply #'message (concat "[TDS-AI-DEBUG] " format-string) args)))

;; Debug buffer function
(defun tds-ai-debug-log-prompt (prompt prompt-point)
  "Log PROMPT to debug buffer with context about PROMPT-POINT."
  (when tds-ai-author-debug
    (with-current-buffer (get-buffer-create tds-ai-author-debug-buffer)
      (goto-char (point-max))
      (insert (format "\n\n=== AI PROMPT at position %d ===\n" prompt-point))
      (insert (format "Time: %s\n" (format-time-string "%Y-%m-%d %H:%M:%S")))
      (insert (format "Model: %s\n" (or gptel-model tds-ai-author-gptel-model)))
      (insert (format "Length: %d chars\n" (length prompt)))
      (insert "--- PROMPT CONTENT ---\n")
      (insert prompt)
      (insert "\n--- END PROMPT ---\n"))
    ;; Auto-display the debug buffer
    (display-buffer tds-ai-author-debug-buffer)
    (tds-ai-debug "Logged prompt to debug buffer")))

;; Helper functions for prompt detection and parsing
(defun tds-ai-author-get-bracketed-text ()
  "Find and return bracketed text near point.
Returns a cons cell (start . end) of buffer positions or nil if not found."
  (save-excursion
    (let (start end)
      ;; Go to beginning of bracket if not already there
      (when (not (looking-at "\\["))
        (search-backward "[" (line-beginning-position) t))
      (when (looking-at "\\[")
        (setq start (point))
        ;; Find closing bracket
        (when (search-forward "]" (line-end-position) t)
          (setq end (point))
          ;; Return the positions
          (cons start end))))))

(defun tds-ai-author-find-ai-prompt-at-point ()
  "Find AI[] prompt at or before point.
Returns the AI prompt as a string or nil if not found."
  (tds-ai-debug "Searching for AI prompt at current point: %s" (point))
  (let ((bounds (tds-ai-author-get-bracketed-text)))
    (if (not bounds)
        (progn
          (tds-ai-debug "No bracketed text found")
          nil)
      (tds-ai-debug "Found bracketed text: %s to %s" (car bounds) (cdr bounds))
      ;; Sanity check that it is prefixed with a latex comment
      (save-excursion
        (goto-char (car bounds))
        (backward-char (length tds-ai-prompt-prefix))
        (if (looking-at (regexp-quote tds-ai-prompt-prefix))
            (let ((prompt (concat "AI" (buffer-substring-no-properties
                                       (car bounds) (cdr bounds)))))
              (tds-ai-debug "Found properly prefixed AI prompt: %s" prompt)
              prompt)
          (progn
            (tds-ai-debug "Bracketed text not properly prefixed with '%s'"
                         tds-ai-prompt-prefix)
            nil))))))

(defun tds-ai-author-find-all-ai-prompts (start end)
  "Find all AI[] prompts in region between START and END.
Returns a list of (position . prompt-string) for each prompt."
  (tds-ai-debug "Finding all AI prompts between %s and %s" start end)
  (save-excursion
    (let ((prompts '()))
      (goto-char start)
      ;; Search for lines starting with the prefix
      (while (re-search-forward (concat "^" (regexp-quote tds-ai-prompt-prefix) "\\[") end t)
        (let ((prompt-line-start (match-beginning 0)))
          ;; Move to just after the prefix to find the brackets
          (goto-char (+ prompt-line-start (length tds-ai-prompt-prefix)))
          (let ((bounds (tds-ai-author-get-bracketed-text)))
            (when bounds
              ;; Construct the full AI[...] prompt
              (let ((prompt-string (concat "AI" (buffer-substring-no-properties
                                                 (car bounds) (cdr bounds)))))
                (tds-ai-debug "Found AI prompt at %s: %s" prompt-line-start prompt-string)
                (push (cons prompt-line-start prompt-string) prompts))
              ;; Move past this prompt to continue searching
              (goto-char (cdr bounds))))))
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

;; TODO: Add tds-edit-ai-response function that integrates with paste-and-ediff-clipboard-region
;; This would allow editing AI responses using external tools

;; LLM interaction functions
(defun tds-ai-author-replace-placeholder-with-response (insertion-marker response version count dispatch-time)
  "Replace placeholder at INSERTION-MARKER with RESPONSE.
Returns t if successful, nil if marker invalid."
  (if (not (marker-buffer insertion-marker))
      (progn
        (tds-ai-debug "Marker no longer valid, cannot replace placeholder")
        nil)
    (with-current-buffer (marker-buffer insertion-marker)
      (save-excursion
        (goto-char (marker-position insertion-marker))
        ;; We should be looking at the placeholder airesponse block
        ;; Find its bounds
        (if (not (looking-at (regexp-quote tds-response-latex-prefix)))
            (progn
              (tds-ai-debug "Expected to find airesponse block at marker, but didn't")
              nil)
          ;; Find the end of this block
          (let ((block-start (point)))
            (if (not (re-search-forward (regexp-quote tds-response-latex-suffix) nil t))
                (progn
                  (tds-ai-debug "Could not find end of placeholder block")
                  nil)
              ;; Delete the placeholder block
              (let ((block-end (point))
                    (receipt-time (format-time-string "%Y-%m-%d %H:%M:%S"))
                    (model-name (or gptel-model tds-ai-author-gptel-model "unknown")))
                (delete-region block-start block-end)
                ;; Insert the real response with bookending comments
                (goto-char block-start)
                (insert (format "%s%s\n%% Dispatched: %s, Model: %s [Version %d of %d]\n%s\n%% Received: %s\n%s"
                               tds-response-latex-prefix
                               tds-response-latex-off
                               dispatch-time
                               model-name
                               version
                               count
                               response
                               receipt-time
                               tds-response-latex-suffix))
                (tds-ai-debug "Replaced placeholder with actual response")
                t))))))))

(defun tds-ai-author-handle-gptel-response (response info)
  "Handle the response from gptel.
RESPONSE is the text from the AI.
INFO is a plist containing additional information."
  (let* ((context-data (plist-get info :context))
         (buffer (plist-get context-data :buffer))
         (insertion-marker (plist-get context-data :insertion-marker))
         (version (plist-get context-data :version))
         (count (plist-get context-data :count))
         (dispatch-time (plist-get context-data :dispatch-time)))

    (tds-ai-debug "Received response for version %d of %d" version count)

    ;; Check if buffer still valid
    (if (not (buffer-live-p buffer))
        (progn
          (tds-ai-debug "Buffer no longer valid, dropping response")
          (message "Warning: Buffer deleted, dropping response %d of %d"
                   version count))

      ;; Replace placeholder with actual response
      (if (tds-ai-author-replace-placeholder-with-response
           insertion-marker response version count dispatch-time)
          (message "Generated response %d of %d" version count)
        (message "Warning: Could not insert response %d of %d" version count))

      ;; Clean up the marker
      (set-marker insertion-marker nil)
      (tds-ai-debug "Marker cleaned up for version %d" version))))

;; Main processing functions
(defun tds-ai-author-process-ai-prompt (prompt-point prompt-string)
  "Process AI prompt at PROMPT-POINT with content PROMPT-STRING.
Generates response(s) and inserts them after the prompt."
  (tds-ai-debug "Processing AI prompt at %s: %s" prompt-point prompt-string)
  (let* ((parsed (tds-ai-author-parse-ai-prompt prompt-string))
         (count (plist-get parsed :count))
         (prompt-text (plist-get parsed :prompt))
         (is-duplex (plist-get parsed :is-duplex))
         (current-buffer-ref (current-buffer))
         (dispatch-time (format-time-string "%Y-%m-%d %H:%M:%S"))
         (model-name (or gptel-model tds-ai-author-gptel-model "unknown")))

    (tds-ai-debug "Getting context for point %s" prompt-point)
    (let ((context (tds-ai-context-get-context prompt-point)))
      (tds-ai-debug "Context retrieved, assembling prompt")
      (let ((full-prompt (tds-ai-prompt-assemble context prompt-text)))
        (tds-ai-debug "Prompt assembled (%d chars), invoking LLM" (length full-prompt))

        ;; Check prompt length and warn if needed
        (cond
         ((> (length full-prompt) tds-ai-author-prompt-danger-length)
          (message "WARNING: Prompt is very long (%d chars) - may exceed model limits!"
                   (length full-prompt)))
         ((> (length full-prompt) tds-ai-author-prompt-max-length)
          (message "Warning: Prompt is long (%d chars) - consider reducing context"
                   (length full-prompt))))

        ;; Log to debug buffer
        (tds-ai-debug-log-prompt full-prompt prompt-point)

        ;; Save debug prompt to file if configured
        (when tds-ai-author-debug
          (with-temp-file tds-ai-author-debug-file
            (insert full-prompt))
          (tds-ai-debug "Saved prompt to %s" tds-ai-author-debug-file))

        ;; Insert placeholder blocks and create markers
        (save-excursion
          (goto-char prompt-point)
          (end-of-line)

          ;; For non-duplex single response, clear existing first
          (when (and (= count 1) (not is-duplex))
            (let ((existing (tds-ai-author-find-immediate-response (point))))
              (when existing
                (tds-ai-debug "Clearing existing response before inserting placeholder")
                (delete-region (car existing) (cdr existing)))))

          ;; Create placeholder blocks and markers for each version
          (let ((markers '()))
            (dotimes (i count)
              (let ((version-num (1+ i)))
                ;; Insert placeholder block
                (insert (format "\n%s%s\n"
                               tds-response-latex-prefix
                               tds-response-latex-off))
                (insert (format "%% Dispatched: %s, Model: %s [Version %d of %d]\n"
                               dispatch-time model-name version-num count))
                (insert tds-response-placeholder-text)
                (insert (format "\n%s" tds-response-latex-suffix))

                ;; Create marker pointing to start of this block
                (save-excursion
                  (re-search-backward (regexp-quote tds-response-latex-prefix) nil t)
                  (let ((marker (point-marker)))
                    (push marker markers)
                    (tds-ai-debug "Created marker %d at position %s"
                                 version-num (marker-position marker))))))

            ;; Fire off all requests in parallel
            (setq markers (nreverse markers))  ; Put in correct order
            (dotimes (i count)
              (let ((version-num (1+ i))
                    (version-marker (nth i markers)))
                (tds-ai-debug "Sending request %d of %d to gptel" version-num count)

                (let ((callback-context (list :buffer current-buffer-ref
                                            :insertion-marker version-marker
                                            :version version-num
                                            :count count
                                            :dispatch-time dispatch-time
                                            :is-duplex is-duplex)))
                  (gptel-request
                   full-prompt
                   :callback 'tds-ai-author-handle-gptel-response
                   :context callback-context))))

            (message "Generating %d response%s in parallel..."
                    count (if (> count 1) "s" ""))))))))

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
          (message "No AI[] prompt found at point (must be prefixed with '%s')"
                   tds-ai-prompt-prefix))
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
          (message "No AI[] prompts found in buffer (must be prefixed with '%s')"
                   tds-ai-prompt-prefix))
      (tds-ai-debug "Processing %d prompts" (length prompts))
      (dolist (prompt-info prompts)
        (let ((prompt-pos (car prompt-info))
              (prompt-string (cdr prompt-info)))
          (tds-ai-debug "Processing prompt at %s: %s" prompt-pos prompt-string)
          (tds-ai-author-process-ai-prompt prompt-pos prompt-string)))
      (message "Launched processing for %d AI[] prompts" (length prompts)))))

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

;; TODO: Add tds-edit-prompt-template function for interactive template editing
;; This would create a buffer for editing the prompt template used by tds-ai-prompt

;; TODO: Add tds-insert-context-template function for quick context markup insertion
;; This would help users quickly insert SET/ADD/DROP directives with proper formatting

;;;###autoload
(defun tds-ai-author-show-debug-buffer ()
  "Display the AI prompt debug buffer."
  (interactive)
  (if (get-buffer tds-ai-author-debug-buffer)
      (display-buffer tds-ai-author-debug-buffer)
    (message "No debug buffer exists. Enable debug mode and process a prompt first.")))

(provide 'tds-v3-ai-author)
;;; tds-v3-ai-author.el ends here
