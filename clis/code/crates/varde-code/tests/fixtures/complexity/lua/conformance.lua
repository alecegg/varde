function if_else_if_else(value)
  if value > 0 then
    return 1
  elseif value < 0 then
    return -1
  else
    return 0
  end
end

function else_if_body_nesting(value)
  if value > 0 then
    return 1
  elseif value < 0 then
    if value < -10 then return -2 end
  end
  return 0
end

function else_body_nesting(value)
  if value > 0 then
    return 1
  else
    if value < -10 then return -2 end
  end
  return 0
end

function nested_if_nesting(a, b)
  if a then
    if b then return true end
  end
  return false
end

function loops(values)
  for i = 1, #values do
    for _, value in ipairs(values) do
      while value > 0 do
        repeat value = value - 1 until value == 0
      end
    end
  end
end

function early_return_zero(value)
  if value < 0 then return 0 end
  return value
end

function logical_run_same(a, b, c)
  return a and b and c
end

function logical_run_mixed(a, b, c)
  return a and b or c
end

function logical_negated_run(a, b, c)
  if a and not (b and c) then return true end
  return false
end

function logical_run_across_lambda(a, b, c)
  return a and
    (function()
      return b and c
    end)()
end

function lambda_nesting(flag)
  local callback = function()
    if flag then return true end
    return false
  end
  return callback()
end

function named_nested_function(value)
  local function inner()
    if value then return 1 end
    return 0
  end
  return inner()
end

function condition_nesting(flag)
  if (
    function()
      if flag then return true end
      return false
    end
  )() then
    return 1
  end
  return 0
end

function goto_or_labeled_jump(value)
  if value then goto done end
  ::done::
  return 0
end

local function recursion_direct(n)
  if n > 0 then return recursion_direct(n - 1) end
  return 0
end

local function recursion_two_calls(n)
  if n > 0 then
    recursion_two_calls(n - 1)
    recursion_two_calls(n - 2)
  end
end

M = {}
function M.recursion_qualified_self(n)
  if n > 0 then return M.recursion_qualified_self(n - 1) end
  return 0
end
function M:recursion_method_self(n)
  if n > 0 then return self:recursion_method_self(n - 1) end
  return 0
end

function recursion_other_receiver(n)
  if n > 0 then return other.recursion_other_receiver(n - 1) end
  return 0
end

function recursion_in_closure(n)
  local recursion_callback = function() return recursion_in_closure(n - 1) end
  if n > 0 then recursion_callback() end
end

local function recursion_same_file_cycle_a(n)
  if n > 0 then return recursion_same_file_cycle_b(n - 1) end
  return 0
end
local function recursion_same_file_cycle_b(n)
  if n > 0 then return recursion_same_file_cycle_a(n - 1) end
  return 0
end

function recursion_cross_file_zero(n)
  -- cross_file_peer is defined in another file and is absent from this fixture.
  return cross_file_peer(n)
end

-- Adapted spec example: nested loops, nested if, and goto LABEL.
function sum_primes(n)
  local total = 0
  for candidate = 2, n do
    for divisor = 2, candidate do
      if divisor == candidate then
        total = total + candidate
        goto next_candidate
      end
    end
    ::next_candidate::
  end
  return total
end
