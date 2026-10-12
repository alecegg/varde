def if_else_if_else(a, b)
  if a
    1
  elsif b
    2
  else
    3
  end
end

def else_if_body_nesting(a, b, c)
  if a
    1
  elsif b
    if c
      2
    end
  end
end

def else_body_nesting(a, b)
  unless a
    1
  else
    if b
      2
    end
  end
end

def nested_if_nesting(a, b)
  if a
    if b
      1
    end
  end
end

def loops(values)
  for value in values
    while value
      until value
        loop do
          if value
            break
          end
          next
          redo
        end
      end
    end
  end
end

def switch_once(value)
  case value
  when 1
    :one
  when 2
    :two
  else
    :other
  end
end

def ternary(a, b, c)
  a ? b : c
end

def catch_once(value)
  begin
    perform(value)
  rescue IOError, SystemCallError
    recover
    retry
  ensure
    cleanup
  end
end

def try_finally_zero(value)
  begin
    value
  ensure
    cleanup
  end
end

def early_return_zero(value)
  return 0 unless value
  value
end

def logical_run_same(a, b, c)
  a and b and c
end

def logical_run_mixed(a, b, c)
  a and b or c
end

def logical_negated_run(a, b, c)
  a && !(b && c)
end

def logical_run_across_lambda(a, b, c, d)
  a && ->(x) { x && b } && c
end

def null_coalescing_zero(value, fallback)
  value ||= fallback
  value&.to_s
end

def lambda_nesting(value)
  ->(item) { if item; value; end }
  Proc.new do |item|
    if item
      value
    end
  end
end

def named_nested_function(value)
  def nested_inner(item)
    if item
      1
    end
  end
  nested_inner(value)
end

def class_in_method(value)
  class Local
    def read(item)
      if item
        1
      end
    end
  end
  class << self
    def singleton_read(item)
      if item
        1
      end
    end
  end
  Local.new.read(value)
end

def condition_nesting(a, b, c)
  if a ? b : c
    1
  end
end

def compensating_usage_callback(xs)
  xs.each { |x| if x; g(x); end }
end

def recursion_direct(value)
  recursion_direct(value - 1) if value > 0
end

def recursion_two_calls(value)
  if value > 1
    recursion_two_calls(value - 1) + recursion_two_calls(value - 2)
  end
end

class RecursiveMethods
  def recursion_qualified_self(value)
    self.recursion_qualified_self(value - 1) if value > 0
  end

  def recursion_other_receiver(other, value)
    other.recursion_other_receiver(other, value - 1) if value > 0
  end

  def recursion_in_closure(value)
    -> { recursion_in_closure(value - 1) }
  end

  def recursion_same_file_cycle_a(value)
    recursion_same_file_cycle_b(value - 1) if value > 0
  end

  def recursion_same_file_cycle_b(value)
    recursion_same_file_cycle_a(value - 1) if value > 0
  end

  # This peer lives in another file; the one-file fixture cannot resolve it.
  def recursion_cross_file_zero(value)
    recursion_cross_file_peer(value - 1) if value > 0
  end
end

def spec_example_small(value)
  case value
  when 1 then :one
  when 2 then :two
  when 3 then :three
  else :many
  end
end
