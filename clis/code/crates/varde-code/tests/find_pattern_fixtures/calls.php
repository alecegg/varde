<?php
function alpha(...$args) {}
function beta($value) {}
class Receiver {
    function alpha($value) {}
}
alpha(1);
alpha(1, 2);
$objectRef->alpha(3);
beta(4);
