;;; tds-git-mode.el --- Git integration and version navigation -*- lexical-binding: t; -*-

;;; Commentary:
;; Git integration with Magit and WIP functionality
;; Provides easy navigation through file history

;;; Code:

(require 'magit)

;; Enable Magit-wip mode globally for auto-commits
(magit-wip-mode 1)

;; Configure Magit-wip
(setq magit-wip-after-save-mode t
      magit-wip-after-apply-mode t
      magit-wip-before-change-mode nil)  ; This can be noisy

;; Silence the messages
(setq magit-save-repository-buffers 'dontask)

;; Time machine for navigating file history
(use-package git-timemachine
  :ensure t
  :bind (("C-c g t" . git-timemachine)
         ("C-c <" . git-timemachine-show-previous-revision)
         ("C-c >" . git-timemachine-show-next-revision))
  :config
  (setq git-timemachine-abbreviation-length 8
        git-timemachine-show-minibuffer-details t))

;; Alternative: Quick diff against HEAD
(global-set-key (kbd "C-c g d") 'vc-diff)
(global-set-key (kbd "C-c g r") 'vc-revert)

;; Magit quick access
(global-set-key (kbd "C-c g g") 'magit-status)
(global-set-key (kbd "C-c g l") 'magit-log-buffer-file)
(global-set-key (kbd "C-c g b") 'magit-blame)

(provide 'tds-git-mode)
;;; tds-git-mode.el ends here





