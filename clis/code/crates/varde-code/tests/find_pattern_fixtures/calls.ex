defmodule Calls do
  def alpha(_), do: :ok
  def beta(_), do: :ok
  def run do
    alpha(1)
    alpha(1, 2)
    object_ref.alpha(3)
    beta(4)
  end
end
