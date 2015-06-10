;; Finally, deal with colorizing things (font-lock)
;;
;; Add a hook to the font-lock stuff to allow us to add
;; the rules - we just stack our set of rules onto the end
;; of their rules.
;; Since the rules get reset for every mode, we shouldn't
;; need to clean these up - I could be wrong, of course,
;; but so far I haven't run into any problems...
(add-hook
 'font-lock-mode-hook
 '(lambda ()
   (setq font-lock-keywords
         (append font-lock-keywords
                 (cond ( (eq major-mode 'c++-mode)
tds-cplusplus-font-lock-rules )
                       ( (eq major-mode 'c-mode)
tds-cplusplus-font-lock-rules )
                       ( t nil ))))))

;; My initial attempts at customizing the fontlock mode to
;; be more to my liking -- not prettier, uglier, in fact,
;; as I want global and local vars to stand out as nasty,
;; ugly, blinky, flame-encrusted thingies.  And by thingies
;; I mean identifiers.  But you knew that...

;;(make-face 'global-var)
;;(set-face-foreground 'global-var "magenta")

(defvar font-lock-global-variable-face
 'font-lock-global-variable-face
 "Face name to use for global variables.")
(defvar font-lock-instance-variable-face
 'font-lock-instance-variable-face
 "Face name to use for instance variables.")

(defface font-lock-global-variable-face
 '((((class color) (background light)) (:foreground "magenta"))
  (((class color) (background dark)) (:foreground "magenta"))
  (t (:inverse-video t :bold t)))
 "Face to use for global variables ( g_count, g_start, etcetera)"
 :group 'font-lock-highlighting-faces)

(defface font-lock-instance-variable-face
 '((((class color) (background light)) (:foreground "magenta"))
  (((class color) (background dark)) (:foreground "magenta"))
  (t (:inverse-video t :bold t)))
 "Face to use for class instance variables ( count_, start_, etcetera)"
 :group 'font-lock-highlighting-faces)

