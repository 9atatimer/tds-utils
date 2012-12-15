<?php
// Copyright (>>>YEAR<<<) (>>>USER_NAME<<<)
// 
// (>>>COMMENT<<<)
require_once('lib/base.inc.php');

class PageController extends BaseController {
  var $partial;

  function PageController() {
    BaseController::BaseController();
    
    $action = Form::getParameter('cmd');

    switch($action) {
    case '(>>>POINT<<<)':
      $this->partial = // ...
      break;
    default:
      $this->errs[] = 'Invalid command.';
    }

    $this->exportPageGlobals();
  }

  function partial() {
    return $this->partial;
  }

  function parseForm() {
    // $this->member = Form::getParameter('param');
    // ...
  }

  function validateForm() {
    // if (!$this->field) $this->errs[] = 'No required field provided.';

    return (sizeof($this->errs) == 0);
  }

  // Public members...
}

?>