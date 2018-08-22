;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;; JaveScript Edit Mode

(autoload 'js2-mode "js2" nil t)
(add-to-list 'auto-mode-alist '("\\.js$" . js2-mode))

(defun tds-php-mode()
  "Setup php mode the way I like it."
  (interactive)
  (load-library "php-mode.el"))

(provide 'tds-php-mode)


