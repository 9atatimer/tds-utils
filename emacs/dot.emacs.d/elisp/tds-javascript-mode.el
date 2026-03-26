;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;; JaveScript Edit Mode

(use-package js2-mode
  :ensure t
  :mode (("\\.js\\'" . js2-mode)
         ("\\.ts\\'" . js2-mode))
  :interpreter ("node" . js2-mode)
  :config
  (add-hook 'js2-mode-hook
            (lambda ()
              (setq mode-name "js2")  ;; Set a concise mode name
              (flycheck-select-checker 'javascript-eslint)
              (prettier-js-mode)
              (copilot-mode -1)))  ;; Ensure Copilot is turned off
  (add-hook 'after-change-functions #'prettier-js nil t)
  (setq js2-mode-show-parse-errors nil)
  (setq js2-mode-show-strict-warnings nil)
  (setq js2-basic-offset 2)
  (setq js-switch-indent-offset 2)
  (setq js-chain-indent nil))

(provide 'tds-javascript-mode)
