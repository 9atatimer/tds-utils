;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;; Mode for working with the JVM languages

(defun tds-jvm-mode()
 "Setup jvm languages the way I like it"
 (setq indent-tabs-mode nil)
 (setq tab-width 2)
 (setq tab-width 2)
 (menu-bar-mode 1)                        ;; re-enable text menubar as jdee expects it.
 (setq c-basic-offset 2)
 (setq show-trailing-whitespace t)                        ;; call out
 (set-face-attribute 'trailing-whitespace nil             ;; .. but
                     :background tds-face-color-mild)
;; (require 'jdibug)  ;; not CEDET-2.0 compatible. Sad.
 ;; (setq jde-debugger '("JDEbug"))  ;; doesn't seem to like pants
 (setq jde-debugger '("jdb"))
 (setq my-classpath '("." "~tstumpf/workplace/source/science" "~tstumpf/workplace/source/birdcage"))
 (setq jde-sourcepath my-classpth)
  (setq jde-global-classpath my-classpth)

;; (setq jde-bug-server-socket '("5005"))
 (setq jde-db-option-connect-socket '(nil "5005"))
 
)

(autoload 'jde-mode "jde" "JDE mode." t)
(setq auto-mode-alist
      (append '(("\\.java\\'" . jde-mode)) auto-mode-alist))

(add-hook 'skala-mode-hook 'tds-jvm-mode)
(add-hook 'java-mode-hook 'tds-jvm-mode)
