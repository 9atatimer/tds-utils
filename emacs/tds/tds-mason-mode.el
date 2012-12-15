;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;; Mason Edit Mode
(defun tds-htmlmason-mode()
 "Setup html/mason mode they way I like it."
 (interactive)
 (setq indent-tabs-mode nil)
 (setq tab-width 2)
 (setq show-trailing-whitespace t)            ;; call out trailing whitespace..
 (set-face-attribute 'trailing-whitespace nil ;; .. but not too loudly.
                     :background tds-face-color-mild)
 ; Compilation settings
 (set (make-local-variable 'compile-command)  ;; force server to reload content
      "killall -HUP gws")

)


