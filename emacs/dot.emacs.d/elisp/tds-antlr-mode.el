;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;; Antlr Edit Mode

(defun tds-antlr-add-js ()
  (interactive)
  (add-to-list 'antlr-language-alist '(antlr-mode "JavaScript" "\"JavaScript\"" "JavaScript")))

(add-hook 'antlr-mode-hook 'tds-antlr-add-js)

(provide 'tds-antlr-mode)


