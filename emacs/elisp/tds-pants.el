;;; tds-pants.el --- 

;; Copyright 2018 Todd Stumpf
;;
;; Author: tstumpf@tw-172-17-123-227.office.twttr.net
;; Version: $Id: tds-pants.el,v 0.0 2018/03/14 20:52:58 tstumpf Exp $
;; Keywords: 
;; X-URL: not distributed yet

;; This program is free software; you can redistribute it and/or modify
;; it under the terms of the GNU General Public License as published by
;; the Free Software Foundation; either version 2, or (at your option)
;; any later version.
;;
;; This program is distributed in the hope that it will be useful,
;; but WITHOUT ANY WARRANTY; without even the implied warranty of
;; MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
;; GNU General Public License for more details.
;;
;; You should have received a copy of the GNU General Public License
;; along with this program; if not, write to the Free Software
;; Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.

;;; Commentary:

;; 

;; Put this file into your load-path and the following into your ~/.emacs:
;;   (require 'tds-pants)

;;; Code:

(provide 'tds-pants)
(eval-when-compile
  (require 'cl))

(require 'pants)

(use-package pants
  :bind (("C-c b" . pants-find-build-file)
         ("C-c r" . pants-run-binary)
         ("C-c t" . pants-run-test))
  :config
  (progn
    (setq pants-source-tree-root "/Users/tstumpf/workplace/source"
          pants-bury-compilation-buffer t
          pants-extra-args "-q")))




;;;;##########################################################################
;;;;  User Options, Variables
;;;;##########################################################################





;;; tds-pants.el ends here
