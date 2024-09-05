;; Ensure user-emacs-directory is defined, for Emacs versions older than 23
(unless (boundp 'user-emacs-directory)
  (setq user-emacs-directory "~/.emacs.d/"))

;; Avoid deprecated cl package warnings...
(require 'cl-lib)

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
                           ("gnu" . "https://elpa.gnu.org/packages/")
                           )
        gnutls-algorithm-priority "NORMAL:-VERS-TLS1.3"
        url-queue-timeout 30   ;; don't wait forever for packages to download
        )
  (package-initialize))

;; Ensure use-package is installed
(unless (package-installed-p 'use-package)
  (package-refresh-contents)
  (package-install 'use-package))

(eval-when-compile
  (require 'use-package))

(require 'ansi-color)

(defun colorize-compilation-buffer ()
  (when (eq major-mode 'compilation-mode)
    (ansi-color-apply-on-region (point-min) (point-max))))

(add-hook 'compilation-filter-hook 'colorize-compilation-buffer)

;; Explicitly declare exec-path-from-shell as a dependency
(use-package exec-path-from-shell
  :ensure t
  :if (memq window-system '(mac ns x))
  :config
  (exec-path-from-shell-initialize))

;; Use direnv package to handle directory-specific configuration
(use-package direnv
  :ensure t
  :config
  (direnv-mode))

;; Personal customizations
(mapc 'require
      '(tds-look-and-feel tds-kill-confirm tds-edit-modes tds-buffer-control
        tds-mail-mode tds-ediff-mode tds-misc-utils))

(use-package dabbrev
  :ensure nil  ; Ensure nil is used because dabbrev is part of Emacs, not an external package
  :config
  (setq dabbrev-case-replace nil))

(defun copy-whole-buffer-to-clipboard ()
  "Copy the entire buffer to the clipboard."
  (interactive)
  (kill-new (buffer-substring-no-properties (point-min) (point-max)))
  (message "Buffer copied to clipboard"))

(defun open-init-file ()
  "Open the init.el file."
  (interactive)
  (find-file "~/.emacs.d/init.el"))

;; For the moment assume we're in a node project (which for NH is true) and look for package.json
;; for our root directory.
(add-hook 'compilation-mode-hook
          (lambda ()
            (setq default-directory (locate-dominating-file default-directory "package.json"))))


;; configure explicitly the build-in project.el module:
(global-set-key (kbd "C-c p f") 'project-find-file)       ;; Find a file in the project
(global-set-key (kbd "C-c p d") 'project-dired)           ;; Open dired in the project root
(global-set-key (kbd "C-c p s") 'project-shell)           ;; Open a shell in the project root
(global-set-key (kbd "C-c p b") 'project-switch-to-buffer) ;; Switch to a project buffer
(global-set-key (kbd "C-c p k") 'project-kill-buffers)    ;; Kill all project buffers
(global-set-key (kbd "C-c p c") 'project-compile)

(setq project-compilation-buffer-name-function
      (lambda (project)
        (format "*compilation: %s*" (project-root (project-current t)))))

(setq compile-command "npm run test")  ;; Default compile command


;;(use-package jest... ) removed
;; the jest package doesn't integrate with the project compile command, so its
;; functionality is useless to us.
(require 'compile)

;; First regex (the one that's already working)
(defconst vitest-error-regexp
  (rx line-start
      "    at "
      (group-n 1 (+ (not (any ":"))))  ; file path
      ":"
      (group-n 2 (+ digit))            ; line number
      ":"
      (group-n 3 (+ digit))            ; column number
      (or " " "\n"))
  "Regexp to match Vitest error messages.")

;; New regex for parenthesized file paths
(defconst vitest-paren-error-regexp
  (rx line-start
      "    at "
      (+ (not (any "(")))               ; function name (not captured)
      "("
      (group-n 1
        (not (any "node:"))             ; Exclude lines containing "node:"
        (+ (not (any ":"))))            ; file path
      ":"
      (group-n 2 (+ digit))             ; line number
      ":"
      (group-n 3 (+ digit))             ; column number
      ")"
      (or " " "\n"))
  "Regexp to match Vitest parenthesized file name error messages, skipping node.")

;; There are error traces that show node: lines -- we don't want to step into
;; the trace and look at minimized node code... so just skip those error lines
(add-to-list 'compilation-error-regexp-alist-alist
             '(skip-node-frame
               "^[[:space:]]*at .*(node:[^:]*:[0-9]+:[0-9]+)"
               nil nil nil 0))
(add-to-list 'compilation-error-regexp-alist-alist
             '(skip-node-modules
               "^[[:space:]]*at .*\\((file:///[^:]*:[0-9]+:[0-9]+)\\|\\(node_modules/[^:]*:[0-9]+:[0-9]+\\)\\)"
               nil nil nil 0))
(add-to-list 'compilation-error-regexp-alist-alist
             '(skip-unwanted-frames
               "^[[:space:]]*at .*\\((index [0-9]+)\\)"
               nil nil nil 0))

(add-to-list 'compilation-error-regexp-alist-alist
             `(vitest
               ,vitest-error-regexp
               1   ; file name
               2   ; line number
               3   ; column number
               2   ; error type - using 2 for 'error'
               nil  ; hyperlink
               (1 compilation-error-face)))

(add-to-list 'compilation-error-regexp-alist-alist
             `(vitest-paren
               ,vitest-paren-error-regexp
               1   ; file name
               2   ; line number
               3   ; column number
               2   ; error type - using 2 for 'error'
               nil  ; hyperlink
               (1 compilation-error-face)))

;; Add regexes to pattern match, but make sure skip-patterns get added first.
(add-to-list 'compilation-error-regexp-alist 'skip-node-frame)
(add-to-list 'compilation-error-regexp-alist 'skip-node-modules)
(add-to-list 'compilation-error-regexp-alist 'skip-unwanted-frames)
(add-to-list 'compilation-error-regexp-alist 'vitest)
(add-to-list 'compilation-error-regexp-alist 'vitest-paren)

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
      require-final-newline t
      transient-mark-mode t
      truncate-partial-width-windows t
      uniquify-buffer-name-style 'post-forward-angle-brackets
      indent-tabs-mode nil
      split-width-threshold nil)

;; buffer list behavior -- split the screen if it isn't, and if it is,
;; use a different buffer than the current buffer for the buffer list
(defun my-display-buffer-list (buffer alist)
  (let ((window (or (get-buffer-window buffer)
                    (if (one-window-p)
                        (split-window-sensibly)
                      (next-window)))))
    (when window
      (select-window window)
      (switch-to-buffer buffer)
      window)))

(setq display-buffer-alist
      '(("^\\*Buffer List\\*$"
         (my-display-buffer-list)
         (inhibit-same-window . t))))

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

(define-key minibuffer-local-completion-map (kbd "C-w") 'backward-kill-word)
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
  ;;(setq copilot-version "1.33.0")) ;; flaky as of 2024-06-21
(copilot-reinstall-server)

;; We keep the openai key in our local pass tool
(use-package auth-source-pass
  :ensure t
  :config
  (auth-source-pass-enable))

;; Also use chatgpt-shell -- pulls the API key into chatgpt-shell-openai-key
(use-package chatgpt-shell
  :ensure t
  :custom ((chatgpt-shell-openai-key
            (lambda ()
              (auth-source-pass-get 'secret "emacs-chatgpt-shell-key")))))

;; LSP Mode setup
(use-package lsp-mode
  :ensure t
  :init
  (setq lsp-keymap-prefix "C-c l")  ; Change prefix for lsp-command-keymap (default is "s-l")
  :hook ((js-mode . lsp)
         (js2-mode . lsp)
         (typescript-mode . lsp)
         (web-mode . lsp)
         (vue-mode . lsp))
  :commands lsp
  :config
  (setq lsp-prefer-flymake nil)  ; Use flycheck instead of flymake
  (setq lsp-enable-snippet nil)  ; Disable snippets
  (setq lsp-ui-doc-enable nil)   ; Disable inline documentation
  (setq lsp-ui-sideline-enable nil)  ; Disable sideline
  (setq lsp-auto-guess-root t)   ; Automatically guess the project root
  (setq lsp-log-io nil)          ; Disable log of communication between Emacs and language servers
  (setq lsp-restart 'auto-restart)  ; Automatically restart LSP if it crashes
  (setq lsp-enable-symbol-highlighting nil)  ; Disable symbol highlighting
  (setq lsp-enable-on-type-formatting nil)   ; Disable formatting as you type
  (setq lsp-signature-render-documentation nil)  ; Disable documentation in function signatures
  (setq lsp-eslint-enable nil))

(use-package lsp-ui
  :ensure t
  :commands lsp-ui-mode
  :config
  (setq lsp-ui-doc-enable nil)
  (setq lsp-ui-sideline-enable nil)
  (setq lsp-ui-imenu-enable t)
  (setq lsp-ui-flycheck-enable t))

(use-package lsp-treemacs
  :ensure t
  :commands lsp-treemacs-errors-list)

;;;;;;
;;;;;;
;; temporary hacks to try to get emacs to follow prettier standards
;;;;;;
;;;;;;
;; Set global indentation to 2 spaces for JavaScript and Vue files
(setq-default js-indent-level 2)
(setq-default js2-basic-offset 2)
(setq-default web-mode-code-indent-offset 2)
(setq-default web-mode-markup-indent-offset 2)
(setq-default web-mode-css-indent-offset 2)
(setq-default vue-html-indent-level 2)


;; Prettier for code formatting
(use-package prettier-js
  :ensure t
  :hook ((js2-mode . prettier-js-mode)
         (js-mode . prettier-js-mode)
         (web-mode . prettier-js-mode)
         (vue-mode . prettier-js-mode)))
;; Disable auto-indentation in web-mode if it conflicts with Prettier
(add-hook 'web-mode-hook
          (lambda ()
            (setq web-mode-enable-auto-indentation nil)))

;; Magit keybindings
(use-package magit
  :ensure t
  :bind ("C-x g" . magit-status))

(with-eval-after-load 'magit
  (define-key magit-status-mode-map (kbd "M-n") 'magit-section-forward)
  (define-key magit-status-mode-map (kbd "M-p") 'magit-section-backward)

  ;; Set default comment buffer height
  (setq magit-commit-buffer-max-width nil)
  (setq magit-commit-buffer-height 5)
)

(defvar my-ediff-original-buffer nil
  "Stores the original buffer for the paste-and-ediff function.")

(defvar my-ediff-original-start nil
  "Stores the start position of the region for the paste-and-ediff function.")

(defvar my-ediff-original-end nil
  "Stores the end position of the region for the paste-and-ediff function.")

(defun paste-and-ediff-clipboard-region ()
  "Paste the clipboard content into a new buffer, compare with selected region using ediff, and prompt to accept changes."
  (interactive)
  (if (use-region-p)
      (let* ((clipboard-content (current-kill 0))
             (region-content (buffer-substring-no-properties (region-beginning) (region-end)))
             (clipboard-buffer (get-buffer-create "*clipboard*"))
             (region-buffer (get-buffer-create "*region*")))
        (setq my-ediff-original-buffer (current-buffer)
              my-ediff-original-start (region-beginning)
              my-ediff-original-end (region-end))
        (with-current-buffer clipboard-buffer
          (erase-buffer)
          (insert clipboard-content))
        (with-current-buffer region-buffer
          (erase-buffer)
          (insert region-content))
        ;; Run Ediff and apply changes if needed
        (let ((ediff-window-setup-function 'ediff-setup-windows-plain)
              (ediff-ignore-similar-regions t)) ;; Ignore whitespace differences
          (ediff-buffers clipboard-buffer region-buffer)
          (add-hook 'ediff-after-quit-hook-internal
                    (lambda ()
                      (message "Inside ediff hook")
                      (if (yes-or-no-p "Apply changes from clipboard to buffer?")
                          (let ((final-content (with-current-buffer "*clipboard*"
                                                 (buffer-substring-no-properties (point-min) (point-max)))))
                            (with-current-buffer my-ediff-original-buffer
                              (save-excursion
                                (goto-char my-ediff-original-start)
                                (delete-region my-ediff-original-start my-ediff-original-end)
                                (insert final-content))
                              (message "Changes applied from clipboard")))
                        (message "Changes not applied"))
                      ;; Cleanup temporary buffers
                      (when (get-buffer "*clipboard*")
                        (kill-buffer "*clipboard*"))
                      (when (get-buffer "*region*")
                        (kill-buffer "*region*"))
                      ;; Return to the original buffer and position
                      (switch-to-buffer my-ediff-original-buffer)
                      (goto-char my-ediff-original-start)))))
    (message "No region selected")))

(global-set-key (kbd "C-M-v") 'paste-and-ediff-clipboard-region)
(global-set-key (kbd "C-M-y") 'paste-and-ediff-clipboard-region)


;;
;; Let's use cody!
;;

;; cody expects gpg-encryption support, and epa-file:
(require 'epa-file)
(epa-file-enable)
(setq epa-file-cache-passphrase-for-symmetric-encryption nil)  ; Do not cache passphrase
(setq epa-file-select-keys nil)  ; Ensure that Emacs prompts for a passphrase
(setq epa-armor t)  ; Use ASCII armor for encryption (optional)
(setq epa-pinentry-mode 'loopback)  ; Use Emacs for passphrase entry, rather than an external tool


;; ;; Tell `use-package' where to find your clone of `cody.el'.
;; (add-to-list 'load-path (expand-file-name "~/workplace/sourcegraph/emacs-cody"))

;; ;; Cody currently expects a very specifi nodejs version:
;; (setq cody-node-executable "/Users/stumpf/.nvm/versions/node/v20.4.0/bin/node")

;; (require 'uuidgen)  ;; needed for cody
;; (use-package cody
;;   :commands (cody-login cody-restart cody-chat cody-mode)
;;   :hook (prog-mode . cody-mode) ;; enable cody by default
;;   ;; Some common key bindings.
;;   :bind (:map cody-mode-map
;;               ("C-?" . cody-request-completion)
;;               ("<backtab>" . cody-completion-accept-key-dispatch)
;;               ("C-<backtab>" . cody-completion-cycle-next-key-dispatch )
;;               ("C-<tab>" . cody-completion-cycle-prev-key-dispatch )
;;               ("S-C-?" . cody-chat)
;;               ("S-C-g" . cody-quit-key-dispatch))
;;   :init
;;   (setq cody--sourcegraph-host "cody.sourcegraph.com") ; for clarity; this is the default. ;; seems to be used for retrieving the secret from gpg, not for connecting.
;;   (setopt cody-workspace-root "~/workplace/newharbor/newharbor-app")
;;   :config
;;   (defalias 'cody-start 'cody-login))


;; Two things I seem to be doing a lot of -- copy the whole file to a clipboard
;; and editing my init.el
(global-set-key (kbd "C-x C-y") 'copy-whole-buffer-to-clipboard)
(global-set-key (kbd "C-c e i") 'open-init-file)

;;
;;  Misc emacs-UI controlled variables:
;;

(custom-set-variables
 ;; custom-set-variables was added by Custom.
 ;; If you edit it by hand, you could mess it up, so be careful.
 ;; Your init file should contain only one such instance.
 ;; If there is more than one, they won't work right.
 '(indent-tabs-mode nil)
 '(package-selected-packages
   '(uuidgen eslint-fix lsp-mode magit web-mode chatgpt-shell js2-mode terraform-mode quelpa-use-package poly-ruby poly-rst poly-markdown mermaid-mode groovy-mode exec-path-from-shell dtrt-indent copilot bazel)))

(custom-set-faces
 ;; custom-set-faces was added by Custom.
 ;; If you edit it by hand, you could mess it up, so be careful.
 ;; Your init file should contain only one such instance.
 ;; If there is more than one, they won't work right.
 )
