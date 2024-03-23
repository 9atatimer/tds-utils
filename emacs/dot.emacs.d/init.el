;; Ensure user-emacs-directory is defined, for Emacs versions older than 23
(unless (boundp 'user-emacs-directory)
  (setq user-emacs-directory "~/.emacs.d/"))

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

;; Copilot setup
(use-package copilot
  :ensure t
  :hook (prog-mode . copilot-mode)
  :bind (:map copilot-completion-map
              ("M-<tab>" . copilot-next-completion)
              ("S-<tab>" . copilot-accept-completion)
              ("C-<tab>" . copilot-panel-completion)))