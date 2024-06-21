;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;; Controls which edit modes suit my fancy at the moment
(load-library "tds-font-lock-fonts.el")  ;; defines standard font color mapping

;;;;
;; Tree-Sitter

;; Ensure you have tree-sitter and tree-sitter-langs installed
(use-package tree-sitter
  :ensure t
  :config
  (global-tree-sitter-mode)
  (add-hook 'tree-sitter-after-on-hook #'tree-sitter-hl-mode))

(use-package tree-sitter-langs
  :ensure t
  :after tree-sitter)

;;;;
;; Webmode for vue templates
(use-package web-mode
  :ensure t
  :mode "\\.vue\\'"
  :config
  (setq web-mode-content-types-alist '(("vue" . "\\.vue\\'"))))


;;;;
;; LSP

(use-package typescript-mode
  :ensure t)

(use-package prettier-js
  :ensure t
  :hook (web-mode . prettier-js-mode))

(use-package flycheck
  :ensure t
  :init (global-flycheck-mode))

(use-package lsp-mode
  :ensure t
  :hook (web-mode . lsp)
  :commands lsp)


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
