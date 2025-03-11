;;; tds-claude-code.el --- Manage Claude Coder session in Emacs

(defun tds-launch-claude-in-dir (dir)
  "Launch a new 'claude-coder' ansi-term in the given DIR."
  (let ((default-directory dir))
    (let ((term-buffer (ansi-term "claude")))
      (with-current-buffer term-buffer
        (rename-buffer "*claude-coder*"))
      term-buffer)))

(defun tds-prompt-for-directory ()
  "Prompt the user for a directory, defaulting to the current working directory."
  (read-directory-name "Start in directory: " default-directory))

(defun tds-find-or-launch-claude-term ()
  "Find an existing '*claude-coder*' session or launch a new one in a selected directory."
  (interactive)
  (let ((buffer (get-buffer "*claude-coder*")))
    (if buffer
        (switch-to-buffer buffer)
      (tds-launch-claude-in-dir (tds-prompt-for-directory)))))

(global-set-key (kbd "C-c e c") 'tds-find-or-launch-claude-term)

(provide 'tds-claude-code)
