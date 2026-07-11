;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;; Shell Edit Mode

(defun tds-setup-shell-mode ()
  "Customize shell-mode (aka sh-mode).

Can be called directly, or added to the sh-mode-hook, as you will.
"
  (interactive)
  (setq sh-basic-offset 2)
  )

(add-hook 'sh-mode-hook 'tds-setup-shell-mode)

(provide 'tds-shell-mode)
