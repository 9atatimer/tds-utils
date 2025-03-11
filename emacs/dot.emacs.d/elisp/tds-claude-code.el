;;; tds-claude-code.el --- Manage Claude Coder sessions in Emacs

(defun tds-buffer-name-from-dir (dir)
  "Generate a buffer name from the basename of DIR."
  (concat "*claude-coder-" (file-name-nondirectory (directory-file-name dir)) "*"))

(defun tds-launch-claude-in-dir (dir)
  "Launch a new 'claude-coder' ansi-term in the given DIR.
The buffer name is derived from the directory."
  (let ((default-directory dir)
        (buffer-name (tds-buffer-name-from-dir dir)))
    (let ((term-buffer (ansi-term "claude")))
      (with-current-buffer term-buffer
        (rename-buffer buffer-name))
      term-buffer)))

(defun tds-prompt-for-directory ()
  "Prompt the user for a directory, defaulting to the current working directory."
  (read-directory-name "Start in directory: " default-directory))

(defun tds-find-or-launch-claude-term (&optional arg)
  "Find an existing '*claude-coder*' session or launch a new one.
If called with `C-u`, always start a new session in a chosen directory.
If multiple sessions exist, select one interactively."
  (interactive "P")
  (if arg
      (tds-launch-claude-in-dir (tds-prompt-for-directory))  ;; Always start a new session with C-u
    (let ((existing-buffers (seq-filter (lambda (buf)
                                          (string-match-p "^\\*claude-coder" (buffer-name buf)))
                                        (buffer-list))))
      (cond
       ((= (length existing-buffers) 1) (switch-to-buffer (car existing-buffers))) ;; Only one exists, switch to it
       ((> (length existing-buffers) 1) ;; Multiple exist, ask user
        (switch-to-buffer
         (completing-read "Choose a Claude session: "
                          (mapcar #'buffer-name existing-buffers) nil t)))
       (t (tds-launch-claude-in-dir (tds-prompt-for-directory))))))) ;; No sessions, start a new one

(global-set-key (kbd "C-c e c") 'tds-find-or-launch-claude-term)

(provide 'tds-claude-code)
