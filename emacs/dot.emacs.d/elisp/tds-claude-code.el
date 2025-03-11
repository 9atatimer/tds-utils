;;; tds-claude-code.el --- Manage Claude Coder session in Emacs

(defun tds-find-or-launch-claude-term ()
  "Find an existing ansi-term named '*claude-coder*', or launch a new one."
  (interactive)
  (let ((buffer (get-buffer "*claude-coder*")))
    (if buffer
        (switch-to-buffer buffer)  ;; If session exists, switch to it
      (let ((term-buffer (ansi-term "claude")))  ;; Launch new term
        (with-current-buffer term-buffer
          (rename-buffer "*claude-coder*"))))));; Rename buffer

(global-set-key (kbd "C-c e c") 'tds-find-or-launch-claude-term)

(provide 'tds-claude-code)
