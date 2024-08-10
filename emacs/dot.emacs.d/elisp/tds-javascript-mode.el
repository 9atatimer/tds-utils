;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;; JaveScript Edit Mode

(use-package js2-mode
  :ensure t   ; Make sure js2-mode is installed from a package repository
  :mode ("\\.js\\'" . js2-mode)    ; Associate JS files with js2-mode
  :interpreter ("node" . js2-mode)
  :config
  (add-hook 'js2-mode-hook
            (lambda ()
              (flycheck-select-checker 'javascript-eslint)))
  (setq js2-mode-show-parse-errors nil)
  (setq js2-mode-show-strict-warnings nil))

(provide 'tds-javascript-mode)
