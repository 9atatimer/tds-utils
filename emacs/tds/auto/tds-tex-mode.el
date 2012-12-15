(TeX-add-style-hook "tds-tex-mode"
 (lambda ()
    (TeX-run-style-hooks
     "\" filename \""
     "\" (file-name-sans-extension filename) \"")))

