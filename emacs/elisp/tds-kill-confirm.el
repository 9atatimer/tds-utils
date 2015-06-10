;;
(setq kill-emacs-hook
     '(lambda ()
        (if (not (y-or-n-p "You sure you want to quit?"))
            (top-level)
          (if (get-buffer "*Group*") (gnus-group-exit)))))

(provide 'tds-kill-confirm)


