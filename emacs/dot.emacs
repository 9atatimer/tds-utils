;; Welcome to my .emacs file... let me show you around.
;;    -- Todd Stumpf (stumpf@google.com) Jan 11, 2006

;; Not everything is in this one file -- I've broken things
;; out into other .el files to avoid clutter.
;;
;; Setup the load path to first look for stuff in ~/.emacs.d/test,
;; then fall back to the standard paths.
(defun tds-prefix-load-path()
 "Add personal paths to front of load-path"
 (setq load-path
       (append
        (list
         "~/.emacs.d/test/")
        load-path)))

(tds-prefix-load-path)

(setenv "PATH"
	(concat "~/bin:/srv/droid/android-ndk-r8b:/srv/droid/android-sdk-linux/platform-tools:/srv/droid/android-sdk-linux/tools" (getenv "PATH"))) ;; use in (shell-command)

(require 'diff-mode-) ;; diff-mode extension needs load before diff-mode
(require 'diff-mode)

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

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;; Let the stumpf-ian customization begin
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
(require 'tds-look-and-feel) ;; holds font/face colors I prefer
(require 'tds-kill-confirm)  ;; make sure I meant to hit ^X^C
(require 'tds-edit-modes)    ;; language-specific edit settings I want
(require 'tds-buffer-control);; buffer advice to protect me from myself
(require 'tds-mail-mode)     ;; tweak mail to protect me from myself
(require 'tds-ediff-mode)    ;; trim ediff behavior. keep it simple.
(require 'tds-misc-utils)    ;; things I can't categorize...

(require 'icomplete)                  ;; show dynamic completions in minibuffer
(require 'paren)                      ;; show (matched (nested (parens)))
(require 'uniquify)                   ;; show path on similar buffer names

(require 'css-mode)
(require 'php-mode)

(require 'template)                   ;; let me use pre-defined code snippets
;;(setq template-default-directories  ;; add personal templates...
;; (append (list "~/emacs/templates") ;; .. or skip and ln -s ~/.templates
;; template-default-directories))     ;; to your template depot.
(template-initialize)
(require 'tds-template-advice)        ;; tweak locating template by extension

;(load "~/emacs/elisp/nxml/nxml-mode-20041004/rng-auto.el")

 ;;;;;;;;;;;;;;;;;;;
 ;; Behavior tweaks
(setq font-lock-support-mode 'jit-lock-mode);; fontify in the background
(setq auto-save-default nil)           ;; don't litter disk with foo~ files
(setq find-file-existing-other-name t) ;; avoid multiple buffers aliasing file
(setq next-line-add-newlines nil)      ;; don't append with repeated 'next-line'
(setq inhibit-startup-message t)       ;; don't spam me with startup message
(setq tags-case-fold-search nil)       ;; tags-search is case sensitive
(setq dabbrev-case-replace nil)        ;; preserve case in dabbrev matches.
(setq require-final-newline t)         ;; always end in a newline
(setq transient-mark-mode t)           ;; deselect region when buffer changes
(setq truncate-partial-width-windows t);; line-wrap even in vertical windows
(setq uniquify-buffer-name-style 'post-forward-angle-brackets)

;;(resize-minibuffer-mode)             ;; let minibuffer grow to display options

(setq backup-directory-alist             ;; backup files under ~/emacs/backups
     (list '("." . "~/emacs/backups"))) ;; to make them easier to clean up
(setq backup-by-copying-when-mismatch t) ;; if mv'ing to backup would change
                                        ;; perms, just copy to backup

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
;(tool-bar-mode 0)                        ;; nuke sillier graphic toolbar
(global-font-lock-mode t)                ;; font-lock all buffers that want it
(show-paren-mode t)                      ;; display matching parenthesis
(setq suggest-key-bindings t)            ;; tell me if command is already bound
(setq search-highlight t)                ;; highlights current search match
(setq visible-bell t)                    ;; flash-screen instead of beeping

(setq display-time-interval (* 5 3))     ;; update every 5*3 (15) seconds
(setq display-time-24hr-format t)        ;; use 24 hour (00:00 -> 23:59) format
(display-time)

(line-number-mode 1)                     ;; give me line-numbers in status bar
(column-number-mode 1)                   ;; give me column-numbers in status bar

(ansi-color-for-comint-mode-on)          ;; display colors in shells

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

(global-set-key "\C-w"  'backward-kill-word)         ;; just what I'm used to...
(global-set-key "\C-x_"  'call-last-kbd-macro)        ;; C-( ... C-) then C-_'

(autoload 'gtags-mode "gtags" "" t)
(global-set-key "\M-\." 'gtags-find-tag)
;;(global-set-key [?\M-\C-.] 'google-show-callers)     ;; show callers of function

(global-unset-key "\C-x\C-z")                        ;; I never want to minimize

;; when I'm running on a mac, I want:
;;   the command (apple) key to be a meta key
;;   the option/alt key to be a super key
;;   the control key to be, tada, control
;;   ... nothing bound to hyper.  poor hyper.

(if (string-equal "darwin" system-type)
    (progn
        (setq mac-command-modifier 'meta)
	(setq mac-control-modifier 'control)
	(setq mac-function-modifier 'none)  ;; only exists on laptop, so don't try and use it...
	(setq mac-option-modifier 'super)
	(setq mac-right-option-modifier 'left)  ;; do whatever the left one does (open apple == close apple)
	(setq quacks-like-a-darwin 't)))

(global-unset-key "\C-x\C-z")                        ;; I never want to minimize

