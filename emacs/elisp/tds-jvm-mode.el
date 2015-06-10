;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;; Mode for working with the JVM languages

(defun tds-jvm-mode()
 "Setup jvm languages the way I like it"
 (setq indent-tabs-mode nil)
 (setq tab-width 2)
 (setq tab-width 2)
 (setq jde-debugger JDEbug)
 (menu-bar-mode 1)                        ;; re-enable not-so silly text menubar
 (tool-bar-mode 1)
 (setq c-basic-offset 2)
 (setq show-trailing-whitespace t)                        ;; call out
 (set-face-attribute 'trailing-whitespace nil             ;; .. but
                     :background tds-face-color-mild)
 ;; (require 'jdibug)
  (load "jde")
)

(add-hook 'skala-mode-hook 'tds-jvm-mode)
(add-hook 'java-mode-hook 'tds-jvm-mode)
