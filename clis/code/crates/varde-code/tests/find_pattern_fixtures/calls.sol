pragma solidity ^0.8.0;
contract Calls {
  function alpha(uint a) internal pure {}
  function alpha(uint a, uint b) internal pure {}
  function beta(uint a) internal pure {}
  function run() public {
    alpha(1);
    alpha(1, 2);
    objectRef.alpha(3);
    beta(4);
  }
}
