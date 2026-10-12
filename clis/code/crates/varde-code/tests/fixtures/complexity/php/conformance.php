<?php

function if_else_if_else($a, $b, $c) {
    if ($a) { return 1; }
    elseif ($b) { return 2; }
    else if ($c) { return 3; }
    else { return 4; }
}

function else_if_body_nesting($a, $b, $c) {
    if ($a) { return 1; }
    elseif ($b) {
        if ($c) { return 2; }
    }
    return 0;
}

function else_body_nesting($a, $b) {
    if ($a) { return 1; }
    else { if ($b) { return 2; } }
    return 0;
}

function nested_if_nesting($a, $b, $c) {
    if ($a) { if ($b) { if ($c) { return 1; } } }
    return 0;
}

function loops($items) {
    foreach ($items as $item) {
        while ($item) { break; }
    }
}

function switch_once($value) {
    switch ($value) {
        case 1: return 'one';
        case 2: return 'two';
        default: return 'other';
    }
}

function ternary($a, $b, $c) {
    return $a ? ($b ? 1 : 2) : ($c ? 3 : 4);
}

function catch_once($a) {
    try { risky(); }
    catch (RuntimeException|LogicException $error) {
        if ($a) { return 1; }
    }
    return 0;
}

function try_finally_zero($a) {
    try { act($a); }
    finally { clean(); }
}

function early_return_zero($a) {
    if ($a) { return 1; }
    return 0;
}

function logical_run_same($a, $b, $c) { return $a && $b && $c; }
function logical_run_mixed($a, $b, $c) { return $a && $b || $c; }
function logical_negated_run($a, $b, $c) { return $a && !($b && $c); }

function logical_run_across_lambda($a, $b, $c) {
    $outer = $a && $b;
    $check = fn() => $a && $c;
    return $outer;
}

function null_coalescing_zero($value, $fallback) {
    return $value ?? ($fallback ?: 'default');
}

function lambda_nesting($a) {
    $check = fn() => $a ? 1 : 0;
    return $check();
}

function named_nested_function($a) {
    function nested_helper($value) {
        if ($value) { return 1; }
        return 0;
    }
    return nested_helper($a);
}

function class_in_method($a) {
    $local = new class($a) {
        public function run($value) {
            if ($value) { return 1; }
            return 0;
        }
    };
    return $local->run($a);
}

function condition_nesting($a, $b, $c) {
    if ($a && $b) { if ($c) { return 1; } }
    return 0;
}

function goto_or_labeled_jump($items, $a) {
    foreach ($items as $item) {
        if ($a) { goto done; }
    }
    done:
    return 0;
}

function multi_level_break($items, $a) {
    foreach ($items as $item) {
        while ($item) {
            if ($a) { break 2; }
            else { continue 2; }
        }
    }
    return 0;
}

function recursion_direct($n) {
    if ($n > 0) { return recursion_direct($n - 1); }
    return 0;
}

function recursion_two_calls($n) {
    if ($n > 0) { recursion_two_calls($n - 1); recursion_two_calls($n - 2); }
    return 0;
}

class RecursiveCases {
    public function recursion_qualified_self($n) {
        if ($n > 0) { return self::recursion_qualified_self($n - 1); }
        return 0;
    }

    public function recursion_other_receiver($other, $n) {
        if ($n > 0) { return $other->recursion_other_receiver($other, $n - 1); }
        return 0;
    }

    public function recursion_in_closure($n) {
        $step = function () use ($n) {
            if ($n > 0) { return $this->recursion_in_closure($n - 1); }
            return 0;
        };
        return $step();
    }

    public function recursion_static_qualified($n) {
        if ($n > 0) { return static::recursion_static_qualified($n - 1); }
        return 0;
    }
}

function recursion_same_file_cycle_a($n) {
    if ($n > 0) { return recursion_same_file_cycle_b($n - 1); }
    return 0;
}
function recursion_same_file_cycle_b($n) {
    if ($n > 0) { return recursion_same_file_cycle_a($n - 1); }
    return 0;
}

function recursion_cross_file_zero($n) {
    // Calls missing_peer, which lives in another file and is absent here.
    return missing_peer($n);
}

function getWords($number) {
    switch ($number) {
        case 1: return 'one';
        case 2: return 'a couple';
        case 3: return 'a few';
        default: return 'lots';
    }
}

function sumOfPrimes($max) {
    $total = 0;
    for ($i = 1; $i <= $max; ++$i) {
        for ($j = 2; $j < $i; ++$j) {
            if ($i % $j === 0) { continue 2; }
        }
        $total += $i;
    }
    return $total;
}

function myMethod($condition1, $condition2) {
    try {
        if ($condition1) {
            for ($i = 0; $i < 10; ++$i) {
                while ($condition2) { break; }
            }
        }
    } catch (TypeError|RuntimeException $error) {
        if ($condition2) { recover(); }
    }
}

function overriddenSymbolFrom($classType) {
    if ($classType->isUnknown()) { return null; }
    $unknownFound = false;
    $symbols = $classType->getSymbol()->members()->lookup($name);
    foreach ($symbols as $overrideSymbol) {
        if ($overrideSymbol->isMethod() && !$overrideSymbol->isStatic()) {
            $method = $overrideSymbol;
            if (canOverride($method)) {
                $overriding = checkParameters($method, $classType);
                if ($overriding === null) {
                    if (!$unknownFound) { $unknownFound = true; }
                } elseif ($overriding) {
                    return $method;
                }
            }
        }
    }
    if ($unknownFound) { return null; }
    return null;
}

function addVersion($entry, $txn) {
    while (true) {
        try {
            if ($entry->previous !== null) {
                if ($entry->previous->version > $entry->version) { throw new RollbackError(); }
                if ($txn->isActive()) {
                    foreach ($entry->previousVersions() as $version) {
                        $depends = dependency($version, $txn->status(), 0);
                        if ($depends === TIMED_OUT) { throw new RetryError($version); }
                        if ($depends !== 0 && $depends !== ABORTED) { throw new RollbackError(); }
                    }
                }
            }
            $entry->setPrevious($entry->previous);
            break;
        } catch (RetryError $error) {
            try {
                $depends = dependency($error->version(), $txn->status(), MAX_WAIT);
                if ($depends !== 0 && $depends !== ABORTED) { throw new RollbackError(); }
            } catch (InterruptedError $interrupted) {
                throw new PersistitInterrupted($interrupted);
            }
        } catch (InterruptedError $interrupted) {
            throw new PersistitInterrupted($interrupted);
        }
    }
}

function toRegexp($pattern, $separator) {
    $escaped = '\\' . $separator;
    $result = '';
    $i = str_starts_with($pattern, '/') || str_starts_with($pattern, '\\') ? 1 : 0;
    while ($i < strlen($pattern)) {
        $ch = $pattern[$i];
        if (isSpecial($ch)) {
            appendEscaped($result, $ch);
        } elseif ($ch === '*') {
            if ($i + 1 < strlen($pattern) && $pattern[$i + 1] === '*') {
                if ($i + 2 < strlen($pattern) && isSlash($pattern[$i + 2])) {
                    $result .= '(?:.*' . $escaped . '|)';
                    $i += 2;
                } else {
                    $result .= '.*';
                    ++$i;
                }
            } else {
                $result .= '[^' . $escaped . ']*?';
            }
        } elseif ($ch === '?') {
            $result .= '[^' . $escaped . ']';
        } elseif (isSlash($ch)) {
            $result .= $escaped;
        } else {
            $result .= $ch;
        }
        ++$i;
    }
    return $result;
}

function alternative_syntax($a, $b) {
    if ($a):
        if ($b): return 1; endif;
    else:
        return 0;
    endif;
    return -1;
}

function match_once($value) {
    return match ($value) { 1, 2 => 'small', default => 'other' };
}
