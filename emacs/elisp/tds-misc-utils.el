;;
(defadvice find-file (around confirm-non-existing-files activate)
 "When called interactively, open non-existing files only upon confirmation."
 (interactive "FSwitch to file: ")
 (if (or (not (interactive-p))
         (file-exists-p (ad-get-arg 0))
         (y-or-n-p (format "`%s' does not exist, create? " (ad-get-arg 0))))
     ad-do-it))

(defun locate-function (function &optional NOSUFFIX)
 "Show the full path name of the loaded Emacs library that defines FUNCTION.
This command checks whether FUNCTION is autoloaded, or it searches the
elements of `load-history' to find the library; then calls `locate-
library' to find the file.
Optional second arg NOSUFFIX non-nil means don't add suffixes `.elc' or `.el'
to the specified name LIBRARY (a la calling `load' instead of `load-library')."
 ;; `interactive' form copied from `describe-function' in help.el:
 (interactive
  (let* ((fn (function-called-at-point))
         (enable-recursive-minibuffers t)
         (val (completing-read
               (if fn
                   (format "Describe function (default %s): " fn)
                 "Describe function: ")
               obarray 'fboundp t)))
    (list (if (equal val "")
              fn
            (intern val))
          current-prefix-arg)))
 (let* ((fn-object (symbol-function function))
        (library (if (and (listp fn-object)
                          (eq (car fn-object) 'autoload))
                     (nth 1 fn-object)))
        (history load-history))
   (while (and history (null library))
     (if (memq function (cdr (car history)))
         (setq library (car (car history))))
     (setq history (cdr history)))
   (if library
       (locate-library library)
     (message "Couldn't find it."))))

;; I can never remember multi-occur-yadda-yadda ... I just want to grep in all
;; the existing buffers... make that an easiser mnemonic.
(defalias 'grep-all 'multi-occur-in-matching-buffers)

(provide 'tds-misc-utils)
