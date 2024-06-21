;; Ensure user-emacs-directory is defined, for Emacs versions older than 23
(unless (boundp 'user-emacs-directory)
  (setq user-emacs-directory "~/.emacs.d/"))

;; Avoid the toolbar at the top to save screen real estate
(when (fboundp 'tool-bar-mode)
  (tool-bar-mode -1))

;; Add personal elisp directories to the load-path
(let ((default-directory (concat user-emacs-directory (convert-standard-filename "elisp/"))))
  (add-to-list 'load-path default-directory)
  (normal-top-level-add-subdirs-to-load-path))

;; Keyboard configurations
(global-set-key [delete] 'delete-char)
(global-set-key [kp-delete] 'delete-char)

(when window-system
  (mwheel-install) ; Enable wheelmouse support
  (set-selection-coding-system 'compound-text-with-extensions)) ; Extended compound-text coding for X clipboard

;; Package management setup for Emacs 24 and above
(when (>= emacs-major-version 24)
  (require 'package)
  (setq package-archives '(("melpa-stable" . "https://stable.melpa.org/packages/")
                           ("melpa" . "https://melpa.org/packages/")
                           ("gnu" . "http://elpa.gnu.org/packages/"))
        gnutls-algorithm-priority "NORMAL:-VERS-TLS1.3")
  (package-initialize))

;; Ensure use-package is installed
(unless (package-installed-p 'use-package)
  (package-refresh-contents)
  (package-install 'use-package))

(eval-when-compile
  (require 'use-package))

;; Explicitly declare exec-path-from-shell as a dependency
(use-package exec-path-from-shell
  :ensure t
  :if (memq window-system '(mac ns x))
  :config
  (exec-path-from-shell-initialize))

;; Personal customizations
(mapc 'require
      '(tds-look-and-feel tds-kill-confirm tds-edit-modes tds-buffer-control
        tds-mail-mode tds-ediff-mode tds-misc-utils))

;; Built-in enhancements
(icomplete-mode 1) ; Dynamic completions in minibuffer
(show-paren-mode 1) ; Highlight matching parentheses
(setq uniquify-buffer-name-style 'post-forward-angle-brackets) ; Unique buffer names

;; Backup settings
(setq backup-directory-alist '(("." . "~/emacs/backups"))
      auto-save-file-name-transforms '((".*" "~/emacs/autosaves" t))
      backup-by-copying t
      delete-old-versions t
      kept-new-versions 6
      kept-old-versions 2
      version-control t)

;; Misc settings
(setq font-lock-support-mode 'jit-lock-mode ; Fontify in the background
      find-file-existing-other-name t
      next-line-add-newlines nil
      inhibit-startup-message t
      tags-case-fold-search nil
      dabbrev-case-replace nil
      require-final-newline t
      transient-mark-mode t
      truncate-partial-width-windows t
      uniquify-buffer-name-style 'post-forward-angle-brackets
      indent-tabs-mode nil
      split-width-threshold nil)

;; Disable undesired operations
(mapc (lambda (operation) (put operation 'disabled nil))
      '(narrow-to-page narrow-to-region downcase-region upcase-region eval-expression))

;; macOS specific settings
(when (eq system-type 'darwin)
  (setq mac-command-modifier 'meta
        mac-control-modifier 'control
        mac-option-modifier 'super
        mac-right-option-modifier 'left))

(server-start)

(define-key minibuffer-local-map (kbd "C-w") 'backward-kill-word)
(setq select-enable-clipboard t)
(global-set-key (kbd "M-c") 'clipboard-kill-ring-save)  ;; apple-C to copy

;; Copilot setup
(use-package copilot
  :ensure t
  :hook (prog-mode . copilot-mode)
  :config (setq copilot-idle-delay 0.5)
  :bind (:map copilot-completion-map
              ("s-<tab>" . copilot-next-completion)
              ("S-<tab>" . copilot-accept-completion)
              ("C-<tab>" . copilot-panel-completion)))

;;;; sure, let's be rebels:
(with-eval-after-load 'copilot
  (setq copilot-version "1.22.0"))
  ;;(setq copilot-version "1.36.0"))
(copilot-reinstall-server)

;; We keep the openai key in our local pass tool
(use-package auth-source-pass
  :ensure t
  :config
  (auth-source-pass-enable))

;; Also use chatgpt-shell -- pulls the API key into chatgpt-shell-openapi-key
(use-package chatgpt-shell
  :ensure t
  :custom ((chatgpt-shell-openapi-key
            (lambda ()
              (auth-source-pass-get 'secret "openapi-key")))))

;;;;;;;;;;
;; move this into its own file if it works
;;;;;;;;;;

(defun paste-and-ediff-clipboard-region ()
  "Paste the clipboard content into a new buffer, compare with selected region using ediff, and prompt to accept changes."


(global-set-key (kbd "C-M-v") 'paste-and-ediff-clipboard-region)
(global-set-key (kbd "C-M-y") 'paste-and-ediff-clipboard-region)

;;;;;;;;;;



(custom-set-variables
 ;; custom-set-variables was added by Custom.
 ;; If you edit it by hand, you could mess it up, so be careful.
 ;; Your init file should contain only one such instance.
 ;; If there is more than one, they won't work right.
 '(indent-tabs-mode nil)
 '(package-selected-packages
   '(web-mode chatgpt-shell js2-mode terraform-mode quelpa-use-package poly-ruby poly-rst poly-markdown mermaid-mode groovy-mode exec-path-from-shell dtrt-indent copilot bazel)))

(custom-set-faces
 ;; custom-set-faces was added by Custom.
 ;; If you edit it by hand, you could mess it up, so be careful.
 ;; Your init file should contain only one such instance.
 ;; If there is more than one, they won't work right.
 )

