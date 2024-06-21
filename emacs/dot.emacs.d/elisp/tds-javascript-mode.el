;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;; JaveScript Edit Mode


(use-package js2-mode
  :ensure t   ; Make sure js2-mode is installed from a package repository
  :mode ("\\.js\\'" . js2-mode)    ; Associate JS files with js2-mode
  :interpreter ("node" . js2-mode)
  :config
  (setq js2-mode-show-parse-errors nil)
  (setq js2-mode-show-strict-warnings nil)
  (setq-default js-basic-offset 2)  ; Default indentation
  (setq indent-tabs-mode nil        ; No tabs for indentation
        js-indent-level 2))         ; Specific JS indentation level

(provide 'tds-javascript-mode)
