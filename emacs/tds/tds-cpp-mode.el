;;
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;; C and C++ Moden

;; Sets of rules that I add to the existing rules
;; Look through the font-lock.el file for an explanation
;; on how to format the rules to get them to do what you want.
(defconst tds-cplusplus-font-lock-rules nil
 "Instance data and global variable naming conventions")

(setq tds-cplusplus-font-lock-rules
     (list
      '("[^a-zA-Z0-9]\\(g_[_a-zA-Z0-9]+\\)" . font-lock-global-variable-face)
      '("\\([_a-zA-Z0-9]+_\\)[^a-zA-Z0-9]"  .
font-lock-instance-variable-face)))

;(defun tds-set-gdb-cwd()
;  "Set gdb's working dir to google3"
;  (setq default-directory tds-gdb-default-dir))
;
;(add-hook 'gud-initial-dir 'tds-set-gdb-cwd)

;; Hook the cppmode and set things the way I want them.
(defun tds-cplusplus-mode()
 "Setup c++ mode the way I like it"
 (interactive)
 ; Appearances
 (setq c-basic-offset 2)
 (setq c-tab-always-indent t)
 (setq indent-tabs-mode nil)
 (setq show-trailing-whitespace t)           ;; call out trailing whitespace..
 (set-face-attribute 'trailing-whitespace    ;; .. but not too loudly.
                     nil
                     :background
                     tds-face-color-mild)
 ; Compilation settings
 (local-set-key "\C-xc" 'google-compile)     ;; cd to google3 before compiling
 (set (make-local-variable 'compile-command) ;; use make-dbg by default
      (concat "make-dbg -r "                 ;; .. -r to make it parallel
              (string-replace-match          ;; .. only the current buffer
               "^.*/google3/"
               (file-name-sans-extension buffer-file-name)
               nil)))
 ; Debugging settings
 (set (make-local-variable 'tds-google3-path) ;; full prefix to ./google3/
      (string-replace-match
       "/google3/.*$"
       (file-name-sans-extension buffer-file-name)
       "/google3/"))
 (set (make-local-variable 'gud-gdb-history) ;; gdb needs to be in google3
      (list                                  ;; and have google3 added to
       (concat "gdb -fullname -cd=" tds-google3-path  ;; code search path
               " -directory=" tds-google3-path
               " " (string-replace-match
                    "/google3/"
                    (file-name-sans-extension buffer-file-name)
                    "/google3/bin/"))))
 )


