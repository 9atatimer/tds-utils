;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;; Git revision control system tweaks
;;
;; You'll need to find 'git-wip' and 'git-wip.el' (last seen on github)
;; and 'diff-mode-.el' (last seen on emacswiki) for these tweaks
;; to work swimmingly.
(require 'cl)
(require 'vc)
(load-library "cl-seq")
(load-library "git-wip.el")  ;; if in git, autocommit to git WIP branch on save

;;------------------------------------------------------------------------------
(defvar git-wip-diff-target (list nil nil)
  "The (buffer filename) we are performing a git-wip-diff of.")

(defvar git-wip-diff-commit-id nil
  "The commit-id of the wip commit diffed by git-wip-diff")

(defun null? (x)  "A nicer null."  (null x))

(defun git-wip-do-file-wip-log ()
  "Get list of commits made to the git wip branch of the cwd (newer to older)."
  ; commit lines look like:
  ;commit a5f6ba19b0c2577a879f8f686c44f0444cb42bd9
  (if (null? git-wip-diff-target)
      (message "Call git-wip-diff on a buffer first.")
    (remove-if 'null?
	       (mapcar (function (lambda (x)
				   (if (string-match
					"commit \\([0-9a-f]\\{40\\}\\)" x)
				       (match-string 1 x))))
		       (split-string (if (null? nil) ;;(second git-wip-diff-target)
					 (vc-git--run-command-string nil "wip" "log")
				       (vc-git--run-command-string
					(second git-wip-diff-target)
					"wip" "log" "--"))
				     "\n")))))

(defun git-wip-diff-reset ()
  "Set the wip-diff-commit-id to the most recent commit, and record the buffer."
  (progn
    (setq git-wip-diff-target (list (current-buffer) (buffer-file-name)))
    (setq git-wip-diff-commit-id (second (git-wip-do-file-wip-log)))))

(defun git-wip-diff-advance-commit-id (commits)
  "Set the wip-diff-commit-id to the next older commit (or most recent if unset)."
  (setq git-wip-diff-commit-id
	(or (cadr (member git-wip-diff-commit-id commits))
	    (or (ding) 
		git-wip-diff-commit-id))))

(defun git-wip-diff-older-commit-id ()
  "Set the wip-diff-commit-id to the next older commit (or most recent if unset)."
  (git-wip-diff-advance-commit-id (git-wip-do-file-wip-log)))

(defun git-wip-diff-newer-commit-id ()
  "Set the wip-diff-commit-id to the next older commit (or most recent if unset)."
  (git-wip-diff-advance-commit-id (reverse (git-wip-do-file-wip-log))))

(defun git-wip-diff-internal (buffer commitA commitB)
  "Displays the diff of version in the buffer against a prior wip commit."
  (save-excursion
    (set-buffer buffer)
    (vc-diff-internal nil (vc-deduce-fileset) commitA commitB)))

(defun git-wip-do-diff (commitA commitB)
  "Do a git wip diff, managing our internal/global variables"
  (if (null? git-wip-diff-target)
      (message "Call git-wip-diff on a buffer first.")
    (git-wip-diff-internal (first git-wip-diff-target)
			   commitA commitB)))

(defun git-wip-diff ()
  "Diff the current buffer against the prior save."
  (interactive)
  (git-wip-do-diff (git-wip-diff-reset) nil))

(defun git-wip-diff-newer ()
  "Show diffs of prior wip commits."
  (interactive)
  (if (null? git-wip-diff-commit-id)
      (message "Call git-wip-diff on a buffer first.")
    (let ((commitB git-wip-diff-commit-id))
      (git-wip-do-diff (git-wip-diff-newer-commit-id) nil)))) ;; nil should be commitB

(defun git-wip-diff-older ()
  "Show diffs of prior wip commits."
  (interactive)
  (if (null? git-wip-diff-commit-id)
      (message "Call git-wip-diff on a buffer first.")
    (let ((commitB git-wip-diff-commit-id))
      (git-wip-do-diff (git-wip-diff-older-commit-id) nil)))) ;; nil should be commitB

;(setq vc-git-diff-switches (list "--color" "--color-words"))  ;; looks gross
;(add-hook 'vc-setup-buffer 'ansi-color-for-comint-mode-on)    ;; doesn't help

;; hook diff-mode so new bindings to fwd/bck are available
(defun tds-git-diff-mode ()
  "Set up diff mode just the way I like it."
  (interactive)
  (local-set-key (kbd "C-c <") 'git-wip-diff-older)
  (local-set-key (kbd "C-c >") 'git-wip-diff-newer)
  (local-unset-key (kbd "C-c ?"))
)

;; we don't want vc-diff dinking with buffer sizes since the diff length
;; might change from diff to diff.  Without this it shrinks, but never grows.
(defadvice shrink-window-if-larger-than-buffer
  (around dont-shrink-git-diff-windows activate)
  "Don't shrink the window -- git is too fast"
  (unless (string= (buffer-name) "*vc-diff*")
    ad-do-it))

(add-hook 'diff-mode-hook 'tds-git-diff-mode)

;; Set some global bindings that work for me.
(global-set-key (kbd "C-c ?") 'git-wip-diff)
(global-set-key (kbd "C-c <") 'git-wip-diff-older)
(global-set-key (kbd "C-c >") 'git-wip-diff-newer)

(provide 'tds-git-mode)
