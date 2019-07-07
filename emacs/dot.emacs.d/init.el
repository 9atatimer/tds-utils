; If we run on something older than emacs 23, we'll want this:
(unless (boundp 'user-emacs-directory)
  (defvar user-emacs-directory "~/.emacs.d/"))

; Add our personal elisp to the load-path so we can find it.
(add-to-list 'load-path
             (concat user-emacs-directory (convert-standard-filename "elisp/")))
(add-to-list 'load-path
             (concat user-emacs-directory (convert-standard-filename "elisp/jdee/lisp/")))
(add-to-list 'load-path
             (concat user-emacs-directory (convert-standard-filename "elisp/jdibug/")))


;;(setq jde-check-version-flag nil)
;;(define-obsolete-function-alias 'make-local-hook 'ignore "21.1")
;;(unless (fboundp 'semantic-format-prototype-tag-java-mode)
;;  (defalias 'semantic-format-prototype-tag-java-mode 'semantic-format-tag-prototype-java-mode))
;;(require 'hippie-exp)

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;; Snipped from default .emacs file for this particular redhat install
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;; Set up the keyboard so the delete key on both the regular keyboard
;; and the keypad delete the character under the cursor and to the right
;; under X, instead of the default, backspace behavior.
(global-set-key [delete] 'delete-char)
(global-set-key [kp-delete] 'delete-char)

(when window-system
 (mwheel-install)                         ;; enable wheelmouse support
 (set-selection-coding-system             ;; use extended compount-text
  'compound-text-with-extensions))        ;; coding for X clipboard
;; The above could be used for X vs text (ie 'emacs -nw') conditionals...

;; ELPA is way to handle emacs packages that was incorporated in v24
;; It is a better way to handle modules, but will require some
;; backporting.   http://www.emacswiki.org/emacs/ELPA
;; Get to the package list via:
;;   M-x package-list-packages
;; Look at the mode help (C-h m)
(require 'package)
(when (>= emacs-major-version 24)
  (add-to-list 'package-archives
               '("melpa-stable" . "https://stable.melpa.org/packages/") t)
  (add-to-list 'package-archives
               '("melpa" . "https://melpa.org/packages/") t)
  (add-to-list 'package-archives
               '("gnu" . "http://elpa.gnu.org/packages/") t))

(package-initialize)

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;; Let the stumpf-ian customization begin
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
(require 'tds-look-and-feel) ;; holds font/face colors I prefer
(require 'tds-kill-confirm)  ;; make sure I meant to hit ^X^C
(require 'tds-edit-modes)    ;; language-specific edit settings I want
(require 'tds-buffer-control);; buffer advice to protect me from myself
(require 'tds-mail-mode)     ;; tweak mail to protect me from myself
(require 'tds-ediff-mode)    ;; trim ediff behavior. keep it simple.
;;(require 'tds-tags)          ;; keep tag systems up to date with my changes.
(require 'tds-pants)         ;; the build tool of choice for le Twitter
(require 'tds-misc-utils)    ;; things I can't categorize...

(require 'icomplete)                  ;; show dynamic completions in minibuffer
(require 'paren)                      ;; show (matched (nested (parens)))
(require 'uniquify)                   ;; show path on similar buffer names

;; don't try to use elap packages here; those are only initialized
;; after the init.el is proccessed. 

;;(require 'css-mode)
;;(require 'php-mode)

(require 'template)                   ;; let me use pre-defined code snippets

;;(setq template-default-directories  ;; add personal templates...
;; (append (list "~/emacs/templates") ;; .. or skip and ln -s ~/.templates
;; template-default-directories))     ;; to your template depot.
(template-initialize)
(require 'tds-template-advice)        ;; tweak locating template by extension

; mac-only libraries
(if (string-equal "darwin" system-type)
    (progn
        (require 'exec-path-from-shell)))

;(load "~/emacs/elisp/nxml/nxml-mode-20041004/rng-auto.el")

 ;;;;;;;;;;;;;;;;;;;
 ;; Behavior tweaks
(setq font-lock-support-mode 'jit-lock-mode);; fontify in the background
(setq find-file-existing-other-name t) ;; avoid multiple buffers aliasing file
(setq next-line-add-newlines nil)      ;; don't append with repeated 'next-line'
(setq inhibit-startup-message t)       ;; don't spam me with startup message
(setq tags-case-fold-search nil)       ;; tags-search is case sensitive
(setq dabbrev-case-replace nil)        ;; preserve case in dabbrev matches.
(setq require-final-newline t)         ;; always end in a newline
(setq transient-mark-mode t)           ;; deselect region when buffer changes
(setq truncate-partial-width-windows t);; line-wrap even in vertical windows
(setq uniquify-buffer-name-style 'post-forward-angle-brackets)
(setq-default indent-tabs-mode nil)    ;; death to tabs!

;;(resize-minibuffer-mode)             ;; let minibuffer grow to display options

(setq backup-by-copying                 t
      delete-old-versions               t
      kept-new-versions                 6
      kept-old-versions                 2
      version-control                   t)
(add-to-list 'backup-directory-alist
	     (cons ".*" "~/emacs/backups"))
(setq auto-save-file-name-transforms
	     '((".*" "~/emacs/autosaves" t)))


(put 'narrow-to-page 'disabled nil)      ;; ...
(put 'narrow-to-region 'disabled nil)    ;; things I never want to do that
(put 'downcase-region 'disabled nil)     ;; seem to do horrible, horrible things
(put 'upcase-region 'disabled nil)       ;; when I accidentally do them
(put 'eval-expression 'disabled nil)     ;; ...

(setq grep-command "grep -i ")           ;; change default grep

 ;;;;;;;;;;;;;;;;;;;
 ;; Appearance tweaks (but isn't appearance really a form
 ;; of behavior? Makes you think...)
(set-frame-width (selected-frame) 81)    ;; Makes 80-char lines look okay.
(menu-bar-mode 0)                        ;; nuke silly text menubar (puh-leeeez)
(if (fboundp 'tool-bar-mode) (tool-bar-mode 0)) ;; nuke sillier graphic toolbar
(global-font-lock-mode t)                ;; font-lock all buffers that want it
(show-paren-mode t)                      ;; display matching parenthesis
(setq suggest-key-bindings t)            ;; tell me if command is already bound
(setq search-highlight t)                ;; highlights current search match
(setq visible-bell nil)                  ;; flash-the mode line instead of beeping
(setq ring-bell-function (lambda ()
  (invert-face 'mode-line)
  (run-with-timer 0.1 nil 'invert-face 'mode-line)))

(setq display-time-interval (* 5 3))     ;; update every 5*3 (15) seconds
(setq display-time-24hr-format t)        ;; use 24 hour (00:00 -> 23:59) format
(display-time)

(line-number-mode 1)                     ;; give me line-numbers in status bar
(column-number-mode 1)                   ;; give me column-numbers in status bar

(ansi-color-for-comint-mode-on)          ;; display colors in shells

(when (boundp 'Buffer-menu-name-width)
  (setq Buffer-menu-name-width	         ;; with uniquify (and rails filenames)
      (+ Buffer-menu-name-width 10))     ;; you need little more room
  (setq Buffer-menu-size-width 4))       ;; do you look at this col?  Me neither.
(setq Buffer-menu-mode-width 7)	         ;; do you look at this col?  Me neither.


 ;;;;;;;;;;;;;;;;;;;
 ;; Finally, binding things to keys...
(global-set-key [f1]   'template-initialize-new)     ;; use .ext boilerplate
(global-set-key [f2]   'template-expand-template)    ;; add arbitrary template
(global-set-key "\C-xc" 'compile)                    ;; compile current buffer
(global-set-key "\C-c\C-c" 'compile)                 ;; compile current buffer
(global-set-key "\C-s"  'isearch-forward-regexp)     ;; regexp by default
(global-set-key "\M-s"  'isearch-forward)            ;; substring search
(global-set-key "\C-r"  'isearch-backward-regexp)    ;; regexp by default
(global-set-key "\M-r"  'isearch-backward)           ;; substring search

(global-set-key "\C-w"  'backward-kill-word)           ;; just what I'm used to...
(global-set-key "\C-x\C-b"  'buffer-menu-other-window)  ;; again, just me...
(global-set-key "\C-x_"  'call-last-kbd-macro)         ;; C-( ... C-) then C-_'


;;;(load-library "gtags")
;;;(autoload 'gtags-mode "gtags" "" t)
;;; (gtags-mode 1)
;;;(global-set-key "\M-\." 'gtags-find-tag)
;;;;;(global-set-key [?\M-\C-.] 'google-show-callers)     ;; show callers of function

(global-unset-key "\C-x\C-z")                        ;; I never want to minimize

;; TODO: move this to a sub-file
;; Handle ANSI escapes in compilation, as ruby/rails tries to be all
;; colorful and such.  Clearly, its trying to hard, if you ask me.
(require 'ansi-color)
(defun colorize-compilation-buffer ()
  (toggle-read-only)
  (ansi-color-apply-on-region (point-min) (point-max))
  (toggle-read-only))
(add-hook 'compilation-filter-hook 'colorize-compilation-buffer)

;; when I'm running on a mac, I want:
;;   the command (apple) key to be a meta key
;;   the option/alt key to be a super key
;;   the control key to be, tada, control
;;   ... nothing bound to hyper.  poor hyper.
;; plus
;;   I want my shell PATH (not the sys def PATH)
(if (string-equal "darwin" system-type)
    (progn
        (exec-path-from-shell-initialize)	;; set PATH for compile and such
        (setq mac-command-modifier 'meta)
	(setq mac-control-modifier 'control)
	(setq mac-function-modifier 'none)  ;; only exists on laptop, so don't try and use it...
	(setq mac-option-modifier 'super)
	(setq mac-right-option-modifier 'left)  ;; do whatever the left one does (open apple == close apple)
	(setq quacks-like-a-darwin 't)))

(server-start)

(custom-set-variables
 ;; custom-set-variables was added by Custom.
 ;; If you edit it by hand, you could mess it up, so be careful.
 ;; Your init file should contain only one such instance.
 ;; If there is more than one, they won't work right.
 '(package-selected-packages
   (quote
    (rbenv json-mode jinja2-mode terraform-mode yasnippet yaml-mode use-package sbt-mode s mustache-mode groovy-mode ggtags fold-this dash company auto-complete))))
(custom-set-faces
 ;; custom-set-faces was added by Custom.
 ;; If you edit it by hand, you could mess it up, so be careful.
 ;; Your init file should contain only one such instance.
 ;; If there is more than one, they won't work right.
 )
