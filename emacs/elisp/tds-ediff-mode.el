;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;; EDiff Customizatoins and Tweaks

;; Set global default behavior
(setq ediff-window-setup-function 'ediff-setup-windows-plain)
;; No pop-up for ctrl panel
;;(setq ediff-current-diff-face-A (copy-face 'italic 'ediff-current-diff-face-A))
;;(setq ediff-current-diff-face-B (copy-face 'italic 'ediff-current-diff-face-B))
;;(setq ediff-current-diff-face-C (copy-face 'italic 'ediff-current-diff-face-C))

;; Tweak global default behavior
(add-hook 'ediff-load-hook
         (lambda ()
           (set-face-foreground ediff-current-diff-face-A "white")
           (set-face-background ediff-current-diff-face-A "green")
           (make-face-italic    ediff-current-diff-face-A)
           (set-face-foreground ediff-current-diff-face-B "white")
           (set-face-background ediff-current-diff-face-B "blue")
           (make-face-italic    ediff-current-diff-face-B)
           (set-face-foreground ediff-current-diff-face-C "white")
           (set-face-background ediff-current-diff-face-C "red")
           (make-face-italic    ediff-current-diff-face-C)
           ))

(provide 'tds-ediff-mode)
