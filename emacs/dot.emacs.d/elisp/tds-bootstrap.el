;;; tds-bootstrap.el --- 
;;
;; Copyright 2013 Todd Stumpf
;;
;; Author: tstumpf@tw-mbp13-tstumpf.local
;; Version: $Id: bootstrap.el,v 0.0 2013/03/12 01:53:51 tstumpf Exp $
;; Keywords: 

;;; Code:
(eval-when-compile
  (require 'cl-lib))

(defun tds-prefix-load-path()
 "Add personal paths to front of load-path"
 (setq load-path
       (append
        (list
         "~/.emacs.d/test/")
        load-path)))
(tds-prefix-load-path)

(defun tds-prefix-exec-path()
  "Add personal paths to front of load-path"
  (setq exec-path
	(append
	 (list
	  "/opt/twitter/bin")
	 exec-path)))
(tds-prefix-exec-path)

; tool-bar.el may not be loaded on text-only emacs instances.
(unless (boundp 'tool-bar-mode)
   (defun tool-bar-mode(a)
     "A NOOP for compatibility if tool-bar.el isnt standard"
     nil))

(provide 'tds-bootstrap)
;;; bootstrap.el ends here
