;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;; Tex Edit Mode
(use-package auctex
  :ensure t
  :mode ("\\.tex$" . LaTeX-mode)
  :config
  ;; Global settings
  (add-hook 'LaTeX-mode-hook 'flyspell-mode)
  (add-hook 'LaTeX-mode-hook 'LaTeX-math-mode)
  (add-hook 'LaTeX-mode-hook 'turn-on-reftex)
  (add-hook 'LaTeX-mode-hook 'TeX-source-correlate-mode)
  (setq TeX-source-correlate-method 'synctex)
  (setq TeX-auto-save t)
  (setq TeX-parse-self t)
  (setq reftex-plug-into-AUCTeX t)

  ;; Define a viewer-related helper function
  (defun skim-make-url ()
    (concat
     (TeX-current-line)
     " "
     (expand-file-name (funcall file (TeX-output-extension) t)
                       (file-name-directory (TeX-master-file)))
     " "
     (buffer-file-name)))

  ;; macOS-specific configuration
  (when (eq system-type 'darwin)
    (setq TeX-command "latex -synctex=1")
    (setq TeX-view-program-list
          '(("Skim" "/Applications/Skim.app/Contents/SharedSupport/displayline %q")))
    (setq TeX-view-program-selection
          '((output-dvi "open")
            (output-pdf "Skim")
            (output-html "open")))
    (add-hook 'LaTeX-mode-hook
              (lambda ()
                (add-to-list 'TeX-expand-list
                             '("%q" skim-make-url)))))

  ;; Master file guessing
  (defun guess-TeX-master-from-open-buffers (filename)
    "Guess the master file for FILENAME from currently open .tex files."
    (let ((candidate nil)
          (filename (file-name-nondirectory filename)))
      (save-excursion
        (dolist (buffer (buffer-list))
          (with-current-buffer buffer
            (let ((name (buffer-name))
                  (file buffer-file-name))
              (if (and file (string-match "\\.tex$" file))
                  (progn
                    (goto-char (point-min))
                    (if (re-search-forward (concat "\\\\input{" filename "}") nil t)
                        (setq candidate file))
                    (if (re-search-forward (concat "\\\\include{" (file-name-sans-extension filename) "}") nil t)
                        (setq candidate file))))))))
      (if candidate
          (message "TeX master document: %s" (file-name-nondirectory candidate)))
      candidate))

  (setq TeX-master (lambda (filename) (guess-TeX-master-from-open-buffers filename))))

(provide 'tds-tex-mode)
