#!/usr/bin/perl

$groupd = 000;

while ($groupd <= 254){
     system("ping -q -c 1 -t 1 192.168.123.$groupd");
     $groupd = $groupd + 1;
     }
