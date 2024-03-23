;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;; Controls which edit modes suit my fancy at the moment
(load-library "tds-font-lock-fonts.el")  ;; defines standard font color mapping

(load-library "tds-antlr-mode.el")
(load-library "tds-cpp-mode.el")
(load-library "tds-dired-mode.el")
;;(load-library "tds-git-mode.el")
(load-library "tds-javascript-mode.el")
(load-library "tds-jvm-mode.el")
(load-library "tds-mason-mode.el")
(load-library "tds-perl-mode.el")
(load-library "tds-python-mode.el")
(load-library "tds-shell-mode.el")
(load-library "tds-yaml-mode.el")

;;(load-library "tds-scala-mode.el")
;;(load-library "tds-tex-mode.el")

;; "Standard" file extensions I deal with...
(add-to-list 'auto-mode-alist '("\\.aurora$" . python-mode))
(add-to-list 'auto-mode-alist '("\\.mesos$" . python-mode))
(add-to-list 'auto-mode-alist '("\\.g4$" . antlr-mode))

(provide 'tds-edit-modes)
