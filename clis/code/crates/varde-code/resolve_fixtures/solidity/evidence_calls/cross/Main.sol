import "./Helper.sol";
contract Main {
  function run() public { Helper helperContract = new Helper(); helperContract.helper(); }
}
