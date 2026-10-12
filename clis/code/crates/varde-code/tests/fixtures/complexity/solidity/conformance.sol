// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

interface Other {
    function recursion_other_receiver() external;
}

contract ComplexityFixture {
    Other private other;

    modifier modifier_callable(bool allowed) {
        if (!allowed) revert();
        _;
    }

    function if_else_if_else(bool a, bool b) public pure {
        if (a) {} else if (b) {} else {}
    }

    function else_if_body_nesting(bool a, bool b, bool c) public pure {
        if (a) {} else if (b) { if (c) {} }
    }

    function else_body_nesting(bool a, bool b) public pure {
        if (a) {} else { if (b) {} }
    }

    function nested_if_nesting(bool a, bool b) public pure {
        if (a) { if (b) {} }
    }

    function loops(uint limit) public pure {
        for (uint i = 0; i < limit; i++) {
            while (i < limit) {
                do { i++; } while (i < limit);
            }
        }
    }

    function switch_once(uint value) public pure {
        assembly {
            switch value
            case 0 {}
            case 1 {}
            default {}
        }
    }

    function ternary(bool condition) public pure returns (uint) {
        return condition ? 1 : 0;
    }

    function catch_once() public {
        try this.mayFail() returns (uint result) {} catch Error(string memory reason) {} catch {}
    }

    function mayFail() external pure returns (uint) {
        return 1;
    }

    function early_return_zero() public pure returns (uint) {
        return 1;
    }

    function logical_run_same(bool a, bool b, bool c) public pure returns (bool) {
        return a && b && c;
    }

    function logical_run_mixed(bool a, bool b, bool c) public pure returns (bool) {
        return a && b || c;
    }

    function logical_negated_run(bool a, bool b, bool c) public pure returns (bool) {
        return a && !(b && c);
    }

    function condition_nesting(bool a, bool b, bool c) public pure {
        if (a ? b : c) {}
    }

    function modifier_host() public modifier_callable(true) {}

    constructor() {}

    fallback() external payable {}

    receive() external payable {}

    function yul_if(bool condition) public pure {
        assembly {
            if condition { pop(0) }
        }
    }

    function yul_loop() public pure {
        assembly {
            for { let i := 0 } lt(i, 1) { i := add(i, 1) } { pop(i) }
        }
    }

    function named_nested_function() public pure {
        assembly {
            function inner(x) -> y {
                if lt(x, 1) { y := 0 }
            }
            let result := inner(1)
        }
    }

    function recursion_direct() public {
        recursion_direct();
    }

    function recursion_two_calls() public {
        recursion_two_calls();
        recursion_two_calls();
    }

    function recursion_qualified_self() public {
        this.recursion_qualified_self();
    }

    function recursion_other_receiver() public {
        other.recursion_other_receiver();
    }

    function recursion_overload_delegate() public {
        recursion_overload_delegate(1);
    }

    function recursion_overload_delegate(uint value) public {}

    function recursion_same_file_cycle_a() public {
        recursion_same_file_cycle_b();
    }

    function recursion_same_file_cycle_b() public {
        recursion_same_file_cycle_a();
    }

    function recursion_cross_file_zero() public {
        // This peer lives in another file and is intentionally absent here.
        recursion_cross_file_peer();
    }

    function spec_example_small(uint value) public pure {
        assembly {
            switch value
            case 1 {}
            case 2 {}
            case 3 {}
            default {}
        }
    }
}
