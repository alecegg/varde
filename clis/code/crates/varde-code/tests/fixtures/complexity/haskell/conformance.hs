{-# LANGUAGE CPP #-}
#ifndef VARDE_HASKELL_COMPLEXITY_FIXTURE
#define VARDE_HASKELL_COMPLEXITY_FIXTURE

if_else_if_else a = if a then 1 else if not a then 2 else 3

else_if_body_nesting a b =
  if a then 1 else if b then if a then 2 else 3 else 4

else_body_nesting a b =
  if a then 1 else if b then 2 else (if a then 3 else 4)

nested_if_nesting a b = if a then if b then 1 else 2 else 3

switch_once x = case x of
  0 -> 1
  1 -> 2
  _ -> 3

catch_once action handler = catch action handler

try_finally_zero action cleanup = finally action cleanup

logical_run_same a b c = a && b && c

logical_run_mixed a b c = a && b || c

logical_negated_run a b c = a && not (b && c)

logical_run_across_lambda a xs = a && any (\x -> x > 0 && x < 10) xs

lambda_nesting xs = any (\x -> if x > 0 then True else False) xs

condition_nesting flag = if (if flag then True else False) then 1 else 0

comprehension_or_query xs = length [x | x <- xs, x > 0 && x < 10]

named_nested_function x = outer x
  where
    outer value = local value
    local value = value + 1

let_local_function x = let local value = value + 1 in local x

guard_alternatives n
  | n < 0 = 1
  | n == 0 = 3
  | otherwise = 4

recursion_direct n = if n <= 0 then 0 else recursion_direct (n - 1)

recursion_two_calls n = if n <= 0 then 0 else recursion_two_calls (n - 1) + recursion_two_calls (n - 2)

recursion_qualified_self n = if n <= 0 then 0 else Main.recursion_qualified_self (n - 1)

recursion_other_receiver n = if n <= 0 then 0 else Other.recursion_other_receiver (n - 1)

recursion_in_closure n =
  let step = \x -> if x <= 0 then 0 else recursion_in_closure (x - 1)
  in step n

recursion_same_file_cycle_a n = recursion_same_file_cycle_b n
recursion_same_file_cycle_b n = recursion_same_file_cycle_a n

-- This call names a peer defined in another source file; this single-file fixture has no such binding.
recursion_cross_file_zero n = peer_defined_elsewhere n

multi_clause_recursion 0 = multi_clause_recursion 0
multi_clause_recursion n = multi_clause_recursion (n - 1)

#if FEATURE_ENABLED
preproc_conditional flag = if flag then 1 else 0
#else
-- fallback branch remains covered by the CPP scanner
#endif

spec_example_small x =
  if x > 0 then case x of
    1 -> (\y -> if y > 0 then y else 0) x
    _ -> 2
  else 0

#endif
