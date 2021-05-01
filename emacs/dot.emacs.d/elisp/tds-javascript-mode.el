;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;; JaveScript Edit Mode

(autoload 'js2-mode "js2" nil t)

(defun tds-js2-mode()
  "Setup js2 mode the way I like it"
  (interactive)
  (setq-default js-basic-offset 2)
  (setq indent-tabs-mode nil
        js-indent-level 2)
)

(add-hook 'js2-modehook 'tds-js2-mode)

(add-to-list 'auto-mode-alist '("\\.js$" . js2-mode))

(provide 'tds-javascript-mode)
