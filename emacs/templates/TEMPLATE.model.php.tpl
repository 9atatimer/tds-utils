<?php
// Copyright (>>>YEAR<<<) (>>>USER_NAME<<<)
// 
// (>>>COMMENT<<<)
class (>>>TableName<<<) {
  // A row object
  var $id, (>>>POINT<<<);
}

class (>>>TableName<<<)DAO {
  var $conn;   // The DB Connection

  function (>>>TableName<<<)DAO(&$conn) {
    $this->conn =& $conn;
  }

  function save(&$row) {
    if ($row->id == 0) {
      $this->insert($row);
    } else {
      $this->update($row);
    }
  }

  function get($id) {
    // execute select statement
    // create new row and call getFromResult
    // return row
  }

  function delete(&$row) {
    // execute delete statement
    // set id on row to 0
  }

#-- private functions

  function getFromResult(&$row, $result) {
    // fill row from the database result set
  }

  function update(&$row) {
    // execute update statement here
  }

  function insert(&$row) {
    // generate id (from Oracle sequence or automatically)
    // insert record into db
    // set id on row
  }
}

?>
>>>TEMPLATE-DEFINITION-SECTION<<<
("TableName" "Table: ")