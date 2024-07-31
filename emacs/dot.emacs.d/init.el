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
(setq url-queue-timeout 30)   ;; don't wait forever for packages to download
(when (>= emacs-major-version 24)
  (require 'package)
  (setq package-archives '(("melpa-stable" . "https://stable.melpa.org/packages/")
                           ("melpa" . "https://melpa.org/packages/")
                           ("gnu" . "https://elpa.gnu.org/packages/")
                           )
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
  :hook ((js-mode . lsp)
         (js2-mode . lsp)
         (typescript-mode . lsp)
         (web-mode . lsp)
         (vue-mode . lsp))
  :commands lsp
  :config
  (setq lsp-prefer-flymake nil) ; Use flycheck instead of flymake
  (setq lsp-enable-snippet nil) ; Disable snippets if not needed
  (setq lsp-ui-doc-enable nil) ; Disable inline documentation if it gets in the way
  (setq lsp-ui-sideline-enable nil)) ; Disable sideline if it gets in the way

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

;; Prettier for code formatting
(use-package prettier-js
  :ensure t
  :hook ((js2-mode . prettier-js-mode)
         (js-mode . prettier-js-mode)
         (web-mode . prettier-js-mode)
         (vue-mode . prettier-js-mode)))

;; Magit keybindings
(with-eval-after-load 'magit
  (define-key magit-status-mode-map (kbd "M-n") 'magit-section-forward)
  (define-key magit-status-mode-map (kbd "M-p") 'magit-section-backward))

(defun paste-and-ediff-clipboard-region ()
  "Paste the clipboard content into a new buffer, compare with selected region using ediff, and prompt to accept changes."
  (interactive)
  (if (use-region-p)
      (let ((clipboard-content (current-kill 0))
            (region-content (buffer-substring-no-properties (region-beginning) (region-end)))
            (clipboard-buffer (get-buffer-create "*clipboard*"))
            (region-buffer (get-buffer-create "*region*"))
            (original-buffer (current-buffer))
            (original-start (region-beginning))
            (original-end (region-end)))
        (message "Clipboard buffer created: %s" clipboard-buffer)
        (with-current-buffer clipboard-buffer
          (erase-buffer)
          (insert clipboard-content)
          (message "Inserted clipboard content"))
        (with-current-buffer region-buffer
          (erase-buffer)
          (insert region-content)
          (message "Inserted region content"))
        ;; Run Ediff and apply changes if needed
        (let ((ediff-window-setup-function 'ediff-setup-windows-plain)
              (ediff-ignore-similar-regions t)) ;; Ignore whitespace differences
          (ediff-buffers clipboard-buffer region-buffer)
          (add-hook 'ediff-after-quit-hook-internal
                    (lambda ()
                      (message "Inside ediff hook")
                      (if (yes-or-no-p "Apply changes from clipboard to buffer?")
                          (let ((final-content (with-current-buffer clipboard-buffer
                                                 (buffer-substring-no-properties (point-min) (point-max)))))
                            (with-current-buffer original-buffer
                              (save-excursion
                                (goto-char original-start)
                                (delete-region original-start original-end)
                                (insert final-content))
                              (message "Changes applied from clipboard")))
                        (message "Changes not applied"))
                      ;; Cleanup temporary buffers
                      (kill-buffer clipboard-buffer)
                      (kill-buffer region-buffer)
                      ;; Return to the original buffer and position
                      (switch-to-buffer original-buffer)
                      (goto-char original-start))))))
    (message "No region selected"))

(global-set-key (kbd "C-M-v") 'paste-and-ediff-clipboard-region)
(global-set-key (kbd "C-M-y") 'paste-and-ediff-clipboard-region)

(custom-set-variables
 ;; custom-set-variables was added by Custom.
 ;; If you edit it by hand, you could mess it up, so be careful.
 ;; Your init file should contain only one such instance.
 ;; If there is more than one, they won't work right.
 '(indent-tabs-mode nil)
 '(package-selected-packages
   '(eslint-fix lsp-mode magit web-mode chatgpt-shell js2-mode terraform-mode quelpa-use-package poly-ruby poly-rst poly-markdown mermaid-mode groovy-mode exec-path-from-shell dtrt-indent copilot bazel)))

(custom-set-faces
 ;; custom-set-faces was added by Custom.
 ;; If you edit it by hand, you could mess it up, so be careful.
 ;; Your init file should contain only one such instance.
 ;; If there is more than one, they won't work right.
 )
