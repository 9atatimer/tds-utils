;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;; Controls which edit modes suit my fancy at the moment
(load-library "tds-font-lock-fonts.el")  ;; defines standard font color mapping
;;;;
;; Tree-Sitter setup with auto-installation of grammars
(use-package tree-sitter
  :ensure t
  :config
  (global-tree-sitter-mode)
  (add-hook 'tree-sitter-after-on-hook #'tree-sitter-hl-mode))

(use-package tree-sitter-langs
  :ensure t
  :after tree-sitter
  :config
  ;; Auto-install TypeScript and TSX grammars
  (setq treesit-language-source-alist
        '((typescript "https://github.com/tree-sitter/tree-sitter-typescript" "master" "typescript/src")
          (tsx "https://github.com/tree-sitter/tree-sitter-typescript" "master" "tsx/src")
          (json "https://github.com/tree-sitter/tree-sitter-json" "master")
          (html "https://github.com/tree-sitter/tree-sitter-html" "master")
          (css "https://github.com/tree-sitter/tree-sitter-css" "master")
          (javascript "https://github.com/tree-sitter/tree-sitter-javascript" "master")))
  
  ;; Install grammars if needed
  (dolist (grammar '(typescript tsx javascript json html css))
    (unless (treesit-language-available-p grammar)
      (message "Installing grammar for %s" grammar)
      (treesit-install-language-grammar grammar))))

;; TypeScript and TSX modes with tree-sitter
(use-package typescript-ts-mode
  :mode (("\\.ts\\'" . typescript-ts-mode)
         ("\\.tsx\\'" . tsx-ts-mode))
  :hook ((typescript-ts-mode . lsp-deferred)
         (tsx-ts-mode . lsp-deferred))
  :config
  (setq typescript-indent-level 2))

;; Add association for JS files to use built-in js-ts-mode
(add-to-list 'auto-mode-alist '("\\.js\\'" . js-ts-mode))
(add-hook 'js-ts-mode-hook 'lsp-deferred)

;; Webmode for vue templates
(use-package web-mode
  :ensure t
  :mode "\\.vue\\'"
  :hook (web-mode . lsp-deferred)
  :config
  (add-hook 'web-mode-hook
            (lambda ()
              (when (string-equal "vue" (file-name-extension buffer-file-name))
                (flycheck-select-checker 'javascript-eslint)
                (prettier-js-mode))))
  (setq web-mode-content-types-alist '(("vue" . "\\.vue\\'")))
  (setq web-mode-markup-indent-offset 2)
  (setq web-mode-css-indent-offset 2)
  (setq web-mode-code-indent-offset 2)
  (setq web-mode-script-padding 0)
  (setq web-mode-style-padding 0))

;; LSP configuration
(use-package lsp-mode
  :ensure t
  :commands lsp lsp-deferred
  :hook ((web-mode . lsp-deferred)
         (js-ts-mode . lsp-deferred)
         (typescript-ts-mode . lsp-deferred)
         (tsx-ts-mode . lsp-deferred))
  :init
  (setq lsp-keymap-prefix "C-c l")
  :config
  (setq lsp-prefer-flymake nil)
  (setq lsp-enable-on-type-formatting nil)
  (setq lsp-enable-indentation nil)
  (setq lsp-typescript-format-enable nil) ; let prettier handle formatting
  (setq lsp-headerline-breadcrumb-enable nil)
  (setq lsp-modeline-code-actions-enable nil)
  (setq lsp-modeline-diagnostics-enable nil)
  (setq lsp-keep-workspace-alive nil)
  (setq lsp-log-io nil))

;; Fallback to normal typescript-mode if tree-sitter is unavailable
(use-package typescript-mode
  :ensure t
  :mode (("\\.ts\\'" . typescript-mode)
         ("\\.tsx\\'" . typescript-mode))
  :hook ((typescript-mode . lsp-deferred))
  :config
  (setq typescript-indent-level 2))

(load-library "tds-antlr-mode.el")
(load-library "tds-cpp-mode.el")
(load-library "tds-dired-mode.el")
(load-library "tds-git-mode.el")
(load-library "tds-javascript-mode.el")
(load-library "tds-jvm-mode.el")
(load-library "tds-mason-mode.el")
(load-library "tds-perl-mode.el")
(load-library "tds-python-mode.el")
(load-library "tds-shell-mode.el")
(load-library "tds-yaml-mode.el")
;;(load-library "tds-scala-mode.el")
;;(load-library "tds-tex-mode.el")
;; "Standard" file extensions I deal with...
(add-to-list 'auto-mode-alist '("\\.aurora$" . python-mode))
(add-to-list 'auto-mode-alist '("\\.mesos$" . python-mode))
(add-to-list 'auto-mode-alist '("\\.g4$" . antlr-mode))
(provide 'tds-edit-modes)
