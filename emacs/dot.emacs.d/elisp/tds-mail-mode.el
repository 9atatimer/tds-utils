;;
(defun tds-confirm-mail-send (orig-fun &rest args)
  "Confirm mail sending. Also go to message line so you can see who
mail is going to."
  (goto-char (point-min))
  (if (yes-or-no-p "Send the message? ")
      (apply orig-fun args)
    (exchange-point-and-mark)))
(advice-add 'mail-send-and-exit :around #'tds-confirm-mail-send)

;; no longer needed, I suspect...
;;(setq user-mail-address (concat (user-login-name) "@google.com"))

(provide 'tds-mail-mode)
