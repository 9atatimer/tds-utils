;;

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;; Directory Edit mode
(defun tds-dired-mode()
 "Setup DirEd so I can actually use it"
 (local-set-key "\C-o" 'other-window)
)

(add-hook 'dired-mode-hook 'tds-dired-mode)

