;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;; Perl mode
(defun tds-perl-mode()
 "Setup perl mode the way I like it"
 (setq compile-command (concat "perl -wc " buffer-file-name))
 (setq indent-tabs-mode nil)
 (setq tab-width 2)
 (setq show-trailing-whitespace t)                        ;; call out
trailing whitespace..
 (set-face-attribute 'trailing-whitespace nil             ;; .. but
not too loudly.
                     :background tds-face-color-mild)
 (set (make-local-variable 'compile-command)
      (concat "perl -wc "
              (file-name-sans-extension buffer-file-name)))
)

(add-to-list 'auto-mode-alist '("\\.pm$" . perl-mode))'

(add-hook 'perl-mode-hook 'tds-perl-mode)
