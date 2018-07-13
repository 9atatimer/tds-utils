;;
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;; Hook the yaml-mode and set things the way I want them.
(defun tds-yaml-mode()
 "Setup yaml mode the way I like it"
 (interactive)
 ; Appearances
 ;; (setq c-basic-offset 2)
 ;; (setq c-tab-always-indent t)
 ;; (setq indent-tabs-mode nil)
 ;; (setq show-trailing-whitespace t)           ;; call out trailing whitespace..
 ;; (set-face-attribute 'trailing-whitespace    ;; .. but not too loudly.
 ;;                     nil
 ;;                     :background
 ;;                     tds-face-color-mild)
 (setq python-indent-offset 2)
 )

(add-hook 'yaml-mode-hook 'tds-yaml-mode)

(add-to-list 'auto-mode-alist '("\\.alert$" . yaml-mode))

(provide 'tds-yaml-mode)
