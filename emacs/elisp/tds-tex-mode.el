;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;; Tex Edit Mode

(load-library "AUCTeX")

(add-to-list 'auto-mode-alist '("\\.tex$" . tds-tex-mode))

;(setq newpath (concat "/usr/texbin:" (getenv "PATH")))

;; helper function to try and figure out which file is the main
;; 'master' file when editting multiple tex files.
(defun guess-TeX-master (filename)
  "Guess the master file for FILENAME from currently open .tex files.  (lifted from EmacsWiki on AUCTeX)"
  (let ((candidate nil)
	(filename (file-name-nondirectory filename)))
    (save-excursion
      (dolist (buffer (buffer-list))
	(with-current-buffer buffer
	  (let ((name (buffer-name))
		(file buffer-file-name))
	    (if (and file (string-match "\\.tex$" file))
		(progn
		  (goto-char (point-min))
		  (if (re-search-forward (concat "\\\\input{" filename "}") nil t)
		      (setq candidate file))
		  (if (re-search-forward (concat "\\\\include{" (file-name-sans-extension filename) "}") nil t)
		      (setq candidate file))))))))
    (if candidate
	(message "TeX master document: %s" (file-name-nondirectory candidate)))
    candidate))

(defun skim-make-url () (concat
        (TeX-current-line)
        " "
        (expand-file-name (funcall file (TeX-output-extension) t)
            (file-name-directory (TeX-master-file)))
        " "
        (buffer-file-name)))

;; things to do once globally
;;(add-hook 'LaTeX-mode-hook 'visual-line-mode)  ;; prevents line wrapping.  sucks.
(add-hook 'LaTeX-mode-hook 'flyspell-mode)
(add-hook 'LaTeX-mode-hook 'LaTeX-math-mode)
(add-hook 'LaTeX-mode-hook 'turn-on-reftex)
(add-hook 'LaTeX-mode-hook 'TeX-source-correlate-mode)
(setq TeX-source-correlate-method 'synctex)

(if (eq system-type 'darwin)
    (progn
      (setq TeX-command "latex -syntex=1")
      (setq TeX-view-program-list
	    '(("Skim" "/Applications/Skim.app/Contents/SharedSupport/displayline %q")))
      (setq TeX-view-program-selection
	    '((output-dvi "open")
	      (output-pdf "Skim")
	      (output-html "open")))
      (setq TeX-view-program-list-builtin
	    '(("Preview.app" "open -a Preview.app %o")
	      ("Skim" "open -a Skim.app %o")
	      ("displayline" "displayline %n %o %b")
	      ("open" "open %o")))
      (add-hook 'LaTeX-mode-hook
		(lambda()
		  (add-to-list 'TeX-expand-list
			       '("%q" skim-make-url))))))

;; things to do for each buffer when entering tex-mode
(defun tds-tex-mode()
 "Setup tex editting mode they way I like it."
 (interactive)
 ;; consider hooking up with evince for pdf-back-to-tex mapping.
 (setq-default TeX-master (guess-TeX-master (buffer-file-name)))

 (setq TeX-PDF-mode t)  ;; doesn't do what you'd think...
 (setq TeX-auto-save t)
 (setq TeX-parse-self t)
 (setq reftex-plug-into-AUCTeX t)

 (latex-mode))

(provide 'tds-tex-mode)




