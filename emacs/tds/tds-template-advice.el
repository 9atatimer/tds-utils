;; I really want to be able to match templates based on their full
;; suffix, not just their extension.
;;
;; template.el seems to support only the last .ext as its 'extension'
;; by default, without any way to easily override that behavior.
;; I just overriding the split function to use the first dot, not the
;; last, and all seems to work well enough.
;;
;; Either link your ~/.templates directory to your template depot, or
;; add it (and others) to the template-default-directories var.

(defadvice template-split-filename (around use-full-suffix-for-match freeze)
  "Split the file using the first dot, not the last, as the EXT delimiter"
  (or dir (setq dir (template-make-directory (file-name-directory file))
		file (file-name-nondirectory file)))
; Here's what the original template.el code had:
;  (let* ((ext (string-match "\\.[^.]*\\'" file))
; Here's what I want:
  (let* ((ext (string-match "\\..*\\'" file))
	 (raw (substring file 0 ext))
	 (num (string-match "[^0-9][0-9]+\\'" raw)))
    (if num
	(list dir file
	      (substring raw 0 (1+ num))
	      (substring raw (1+ num))
	      (if ext (substring file ext) ""))
      (setq ad-return-value 
       (list dir file raw "" (if ext (substring file ext) ""))))))

(provide 'tds-template-advice)

