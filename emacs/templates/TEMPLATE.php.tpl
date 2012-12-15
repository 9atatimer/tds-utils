<?php
require_once('control/(>>>Controller<<<).control.php');
$c =& new PageController();
?>
<?php include('partial/head.inc.php') ?>
<body>
<?php include($c->partial()) ?>
</body>
<?php include('partial/closing.inc.php') ?>
>>>TEMPLATE-DEFINITION-SECTION<<<
("Controller" "Page Controller: ")
