;; Various code tag systems

;;;;;;;
;; Gnu Global -- ggtags.el (or gtags.el)

;; These hooks (from emacswiki.org) provide automatic updates to the
;; global tags files after saving a file.
(defun gtags-root-dir ()
  "Returns GTAGS root directory or nil if doesn't exist."
  (with-temp-buffer
    (if (zerop (call-process "global" nil t nil "-pr"))
	(buffer-substring (point-min) (1- (point-max)))
      nil)))

(defun gtags-update ()
  "Make GTAGS incremental update"
  (call-process "global" nil nil nil "-u"))

(defun gtags-update-hook ()
  (when (gtags-root-dir)
    (gtags-update)))

;;(add-hook 'after-save-hook #'gtags-update-hook)

;(global-set-key "\M-\." 'gtags-find-tag)
;(global-set-key [?\M-\C-.] 'google-show-callers)     ;; show callers of function

(provide 'tds-tags)
