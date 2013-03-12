(defadvice switch-to-buffer (around confirm-non-existing-buffers activate)
 "When called interactively, switch to non-existing buffers only upon
confirmation."
 (interactive "BSwitch to buffer: ")
 (if (or (not (interactive-p))
         ;;
         ;; If the buffer exists, do like normal.
         ;;
         (get-buffer (ad-get-arg 0))
         ;;
         ;; If the buffer is *scratch*, let the user create it no
         ;; matter what.
         ;;
         (string= (ad-get-arg 0) "*scratch*")
         ;;
         ;; Now ask 'em if they really wanted to create a buffer.  If
         ;; they do, then just let switch-to-buffer do its stuff.
         ;;
         (y-or-n-p (format "`%s' does not exist, create? " (ad-get-arg 0)))
         ;;
         ;; They didn't, so they must have wanted to switch to
         ;; some existing buffer.  So we give 'em another chance to type
         ;; its name correctly.  But now we can provide a useful default
         ;; value to READ-BUFFER that is probably the buffer they
         ;; intended!  Isn't that cool?
         ;;
         (ad-set-arg 0
                     (read-buffer
                      "Switch to buffer: "
                      (try-completion
                       (ad-get-arg 0)
                       (mapcar '(lambda (buf)
                                  (list (buffer-name buf)))
                               (buffer-list)))
                      t)))
     ad-do-it))

(defadvice switch-to-buffer (after make-scratch-buffer-lisp activate)
 "Make sure *scratch* buffer is always in lisp-interaction-mode."
 (if (string= (buffer-name) "*scratch*")
     (lisp-interaction-mode)))

(defadvice switch-to-buffer-other-window
 (around confirm-non-existing-buffers activate)
 "When called interactively, switch to non-existing buffers only upon
confirmation."
 (interactive "BSwitch to buffer: ")
 (if (or (not (interactive-p))
         ;;
         ;; If the buffer exists, do like normal.
         ;;
         (get-buffer (ad-get-arg 0))
         ;;
         ;; If the buffer is *scratch*, let the user create it no
         ;; matter what.
         ;;
         (string= (ad-get-arg 0) "*scratch*")
         ;;
         ;; Now ask 'em if they really wanted to create a buffer.  If
         ;; they do, then just let switch-to-buffer do its stuff.
         ;;
         (y-or-n-p (format "`%s' does not exist, create? " (ad-get-arg 0)))
         ;;
         ;; They didn't, so they must have wanted to switch to
         ;; some existing buffer.  So we give 'em another chance to type
         ;; its name correctly.  But now we can provide a useful default
         ;; value to READ-BUFFER that is probably the buffer they
         ;; intended!  Isn't that cool?
         ;;
         (ad-set-arg 0
                     (read-buffer
                      "Switch to buffer: "
                      (try-completion
                       (ad-get-arg 0)
                       (mapcar '(lambda (buf)
                                  (list (buffer-name buf)))
                               (buffer-list)))
                      t)))
     ad-do-it))

(defadvice switch-to-buffer-other-window
 (after make-scratch-buffer-lisp activate)
 "Make sure *scratch* buffer is always in lisp-interaction-mode."
 (if (string= (buffer-name) "*scratch*")
     (lisp-interaction-mode)))

(provide 'tds-buffer-control)
