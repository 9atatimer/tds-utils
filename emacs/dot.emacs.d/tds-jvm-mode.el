;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;; Mode for working with the JVM languages

(defun tds-jvm-mode()
 "Setup jvm languages the way I like it"
 (setq indent-tabs-mode nil)
 (setq tab-width 2)
 (setq show-trailing-whitespace t)                        ;; call out
 (set-face-attribute 'trailing-whitespace nil             ;; .. but
                     :background tds-face-color-mild)
)

(add-hook 'skala-mode-hook 'tds-jvm-mode)
(add-hook 'java-mode-hook 'tds-jvm-mode)
