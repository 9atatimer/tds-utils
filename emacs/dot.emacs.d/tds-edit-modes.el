;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;; Controls which edit modes suit my fancy at the moment

(load-library "php-mode.el")  ;;

(load-library "tds-font-lock-fonts.el")  ;; defines standard font color mapping

(load-library "tds-cpp-mode.el")
(add-hook 'c++-mode-hook 'tds-cplusplus-mode)

(load-library "tds-perl-mode.el")
(add-hook 'perl-mode-hook 'tds-perl-mode)

(load-library "tds-dired-mode.el")
(add-hook 'dired-mode-hook 'tds-dired-mode)

(load-library "tds-mason-mode.el")
(add-hook 'html-mode-hook 'tds-htmlmason-mode)

(autoload 'js2-mode "js2" nil t)
(add-to-list 'auto-mode-alist '("\\.js$" . js2-mode))

;; Put .c & .h files into c++ mode as well
(setq auto-mode-alist
     (append (list
              '("\\.c$" . c++-mode)
              '("\\.h$" . c++-mode))
             auto-mode-alist))

;; Put .mhtml & .mc files into HTML/Mason mode
;; Put .tpl files into HTML/Mason mode as well
(setq auto-mode-alist
     (append (list
              '("\\.tpl$"   . html-mode)
              '("\\.mc$"    . html-mode)
              '("\\.mhtml$" . html-mode))
              auto-mode-alist))

;; Put .pm and .pl files in perl
(setq auto-mode-alist
      (append (list
	       '("\\.pm$" . perl-mode))
	      auto-mode-alist))

(provide 'tds-edit-modes)
