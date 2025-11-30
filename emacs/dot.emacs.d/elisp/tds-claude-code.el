;;; tds-claude-code.el --- Manage Claude Coder sessions in Emacs

;; The plan:
;;
;; C-c e c - launches a claude-code in the cwd of the active buffer (or opens it if it exists)
;;
;; Fix-up ansi-term binding so that:
;;
;;  S-RET - generates a '\' 'RET' keycode, which is treated as a newline by claude
;;  C-y   - pastes from the kill-buffer like a paste
;;
;;; tds-claude-code.el --- Manage Claude Coder sessions in Emacs

(defvar tds-claude-launch-function 'tds-invoke-claude-code-in-dir
  "Function to use for launching Claude coder sessions.
Should accept a directory argument.")

;;
;; claude-code reportedly works best in vterm; load it before using claude
(use-package vterm
  :ensure t)

(use-package claude-code
  :ensure t
  :init
  (setq claude-code-terminal-type 'vterm))

(defun tds-buffer-name-from-dir (dir)
  "Generate a buffer name from the basename of DIR."
  (concat "*claude-coder-" (file-name-nondirectory (directory-file-name dir)) "*"))

(defun tds-setup-term-mode-hooks ()
  "Set up term-mode hooks for Claude sessions."
  (add-hook 'term-mode-hook
            (lambda ()
              (define-key term-raw-map (kbd "<S-return>")
                (lambda () (interactive) (term-send-raw-string "\\\n")))
              (define-key term-raw-map (kbd "C-y")
                (lambda () (interactive) (term-send-raw-string (current-kill 0)))))))

(defun tds-launch-claude-in-dir (dir)
  "Launch a new 'claude-coder' ansi-term in the given DIR."
  (tds-setup-term-mode-hooks)
  (let ((default-directory dir)
        (buffer-name (tds-buffer-name-from-dir dir)))
    (let ((term-buffer (ansi-term "claude")))
      (with-current-buffer term-buffer
        (rename-buffer buffer-name))
      term-buffer)))

(defun tds-invoke-claude-code-in-dir (dir)
  "Launch claude-code mode in the given DIR.
Sets the default directory before invoking claude-code."
  (let ((default-directory dir))
    (claude-code)))

(defun tds-prompt-for-directory ()
  "Prompt the user for a directory, defaulting to the current working directory."
  (read-directory-name "Start in directory: " default-directory))

(defun tds-find-or-launch-claude-term (&optional arg)
  "Find an existing '*claude-coder*' session or launch a new one.
If called with `C-u`, always start a new session in a chosen directory.
If multiple sessions exist, select one interactively."
  (interactive "P")
  (if arg
      (funcall tds-claude-launch-function (tds-prompt-for-directory))  ;; Always start a new session with C-u
    (let ((existing-buffers (seq-filter (lambda (buf)
                                          (string-match-p "^\\*claude-coder" (buffer-name buf)))
                                        (buffer-list))))
      (cond
       ((= (length existing-buffers) 1) (switch-to-buffer (car existing-buffers))) ;; Only one exists, switch to it
       ((> (length existing-buffers) 1) ;; Multiple exist, ask user
        (switch-to-buffer
         (completing-read "Choose a Claude session: "
                          (mapcar #'buffer-name existing-buffers) nil t)))
       (t (funcall tds-claude-launch-function (tds-prompt-for-directory))))))) ;; No sessions, start a new one

;; launch claude-code-mode with C-c e c
(global-set-key (kbd "C-c e c") 'tds-find-or-launch-claude-term)

(provide 'tds-claude-code)
