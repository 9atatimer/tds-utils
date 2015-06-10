;;
(defadvice mail-send-and-exit (around confirm-mail-send activate)
 "Confirm mail sending.  Also go to message line so you can see who
mail is going to."
 (interactive "P")
 (beginning-of-buffer)
 (if (yes-or-no-p "Send the message? ")
     ad-do-it
   (exchange-point-and-mark)))

;; no longer needed, I suspect...
;;(setq user-mail-address (concat (user-login-name) "@google.com"))

(provide 'tds-mail-mode)
