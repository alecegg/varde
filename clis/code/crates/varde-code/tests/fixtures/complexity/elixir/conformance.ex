defmodule ComplexityConformance do
  def if_else_if_else(value) do
    if value == :first do
      :one
    else
      if value == :second do
        :two
      else
        :other
      end
    end
  end

  def else_if_body_nesting(value) do
    cond do
      value == :first -> :one
      value == :second -> if(value, do: :nested)
      true -> :other
    end
  end

  def else_body_nesting(value) do
    if value do
      :yes
    else
      :other
      if value == :other, do: :other
    end
  end

  def nested_if_nesting(a, b) do
    if a do
      if b, do: :yes
    end
  end

  def loops(items) do
    for item <- items, item do
      item
    end
  end

  def switch_once(value) do
    case value do
      :one -> 1
      :two -> 2
      _ -> 0
    end
  end

  def catch_once(value) do
    try do
      value.()
    rescue
      ArgumentError -> :argument
      _ -> :other
    catch
      :throw, reason -> reason
    after
      :cleanup
    end
  end

  def try_finally_zero(value) do
    try do
      value
    after
      :cleanup
    end
  end

  def logical_run_same(a, b, c) do
    a && b && c
  end

  def logical_run_mixed(a, b, c) do
    a && b || c
  end

  def logical_negated_run(a, b, c) do
    a && not (b && c)
  end

  def logical_run_across_lambda(a, b, values) do
    a && Enum.any?(values, fn value -> value && b end)
  end

  def lambda_nesting(value) do
    capture = &is_integer/1
    Enum.map([value], fn item -> if item, do: :yes end)
  end

  def anonymous_with_logical(value) do
    fn a, b, c -> a && b || c end
  end

  def with_else(value) do
    with {:ok, result} <- value do
      result
    else
      :error -> :missing
    end
  end

  def guard_legacy_only(value) when value > 0 do
    if value < 4, do: :small
  end

  def class_in_method(value) do
    defmodule NestedInFunction do
      def inner(flag) do
        if flag, do: :yes
      end
    end
    value
  end

  def condition_nesting(value) do
    if if(value, do: true), do: :yes, else: :no
  end

  def comprehension_or_query(a, b, values) do
    for value <- values, a && b && value, do: value
  end

  def recursion_direct(value) do
    if value > 0, do: recursion_direct(value - 1), else: :done
  end

  def recursion_two_calls(value) do
    if value > 0 do
      recursion_two_calls(value - 1)
      recursion_two_calls(value - 2)
    end
  end

  def recursion_qualified_self(value) do
    __MODULE__.recursion_qualified_self(value)
  end

  def recursion_other_receiver(other, value) do
    other.recursion_other_receiver(value)
  end

  def recursion_overload_delegate(value) do
    recursion_overload_delegate(value, :tail)
  end

  def recursion_overload_delegate(value, :tail), do: value

  def multi_clause_self(0), do: multi_clause_self(1)
  def multi_clause_self(value), do: multi_clause_self(value - 1)

  def recursion_in_closure(value) do
    Enum.map([value], fn item -> recursion_in_closure(item) end)
  end

  def recursion_cycle_a(value), do: recursion_cycle_b(value)
  def recursion_cycle_b(value), do: recursion_cycle_a(value)

  def recursion_cross_file_zero(value) do
    # The peer lives in another file and is absent from this one-file fixture.
    peer_in_another_file(value)
  end

  def spec_example_small(value) do
    case value do
      1 -> "one"
      2 -> "a couple"
      3 -> "a few"
      _ -> "lots"
    end
  end

  def spec_example_large(maximum) do
    for i <- 1..maximum, j <- 2..max(i - 1, 2), rem(i, j) == 0 do
      if rem(i, j) == 0, do: :composite
    end
  end

  def guard_nested_nesting(flag, value) do
    if flag do
      case value do
        n when n > 0 -> n
        _ -> 0
      end
    end
  end
end
