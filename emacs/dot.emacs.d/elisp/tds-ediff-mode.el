;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;; EDiff Customizatoins and Tweaks

;; Set global default behavior
(setq ediff-window-setup-function 'ediff-setup-windows-plain)
;; No pop-up for ctrl panel
;;(setq ediff-current-diff-face-A (copy-face 'italic 'ediff-current-diff-face-A))
;;(setq ediff-current-diff-face-B (copy-face 'italic 'ediff-current-diff-face-B))
;;(setq ediff-current-diff-face-C (copy-face 'italic 'ediff-current-diff-face-C))

(defun my-ediff-face-setup ()
  "Set custom faces for ediff mode."
  (set-face-attribute 'ediff-current-diff-A nil :foreground "black" :background "light green" :slant 'italic)
  (set-face-attribute 'ediff-current-diff-B nil :foreground "black" :background "light blue" :slant 'italic)
  (set-face-attribute 'ediff-current-diff-C nil :foreground "black" :background "light red" :slant 'italic)

  (set-face-attribute 'ediff-fine-diff-A nil :foreground "white" :background "dark green" :weight 'bold)
  (set-face-attribute 'ediff-fine-diff-B nil :foreground "white" :background "dark blue" :weight 'bold)
  (set-face-attribute 'ediff-fine-diff-C nil :foreground "white" :background "dark red" :weight 'bold)

  (set-face-attribute 'ediff-odd-diff-A nil :background "light grey")
  (set-face-attribute 'ediff-odd-diff-B nil :background "light grey")
  (set-face-attribute 'ediff-odd-diff-C nil :background "light grey")

  (set-face-attribute 'ediff-even-diff-A nil :background "grey")
  (set-face-attribute 'ediff-even-diff-B nil :background "grey")
  (set-face-attribute 'ediff-even-diff-C nil :background "grey"))

;; Add to ediff-load-hook
(add-hook 'ediff-load-hook 'my-ediff-face-setup)

; To manually apply the face settings, evaluate the following:
;; M-x eval-expression RET (my-ediff-face-setup)

(provide 'tds-ediff-mode)
