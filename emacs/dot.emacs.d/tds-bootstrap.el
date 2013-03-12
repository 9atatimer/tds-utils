;;; bootstrap.el --- 
;;
;; Copyright 2013 Todd Stumpf
;;
;; Author: tstumpf@tw-mbp13-tstumpf.local
;; Version: $Id: bootstrap.el,v 0.0 2013/03/12 01:53:51 tstumpf Exp $
;; Keywords: 

;;; Code:
(eval-when-compile
  (require 'cl))

(defun tds-prefix-load-path()
 "Add personal paths to front of load-path"
 (setq load-path
       (append
        (list
         "~/.emacs.d/test/")
        load-path)))

(tds-prefix-load-path)

(provide 'bootstrap)
;;; bootstrap.el ends here
