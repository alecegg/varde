object ComplexityFixture {
  def if_else_if_else(a: Boolean, b: Boolean): Int =
    if (a) 1 else if (b) 2 else 3

  def else_if_body_nesting(a: Boolean, b: Boolean, c: Boolean): Int =
    if (a) 0 else if (b) { if (c) 1 }

  def else_body_nesting(a: Boolean, b: Boolean): Int =
    if (a) 0 else { if (b) 1 }

  def nested_if_nesting(a: Boolean, b: Boolean): Unit =
    if (a) { if (b) work() }

  def loops(xs: List[Int]): Unit = {
    for (x <- xs) {
      while (x > 0) {
        if (x == 1) ()
      }
    }
  }

  def switch_once(value: Int): Int = value match {
    case 0 => 0
    case 1 => 1
    case _ => 2
  }

  def catch_once(): Unit = {
    try { work() }
    catch {
      case _: IllegalArgumentException => recover()
      case _: RuntimeException => recover()
    }
    finally { cleanup() }
  }

  def try_finally_zero(): Unit = {
    try { work() }
    finally { cleanup() }
  }

  def early_return_zero(a: Boolean): Int = {
    if (a) return 1
    0
  }

  def logical_run_same(a: Boolean, b: Boolean, c: Boolean): Boolean = a && b && c

  def logical_run_mixed(a: Boolean, b: Boolean, c: Boolean): Boolean = a && b || c

  def logical_negated_run(a: Boolean, b: Boolean, c: Boolean): Boolean =
    a && !(b && c)

  def logical_run_across_lambda(a: Boolean, b: Boolean, xs: List[Int]): Boolean =
    a && b && xs.exists(x => x > 0 && x < 3)

  def lambda_nesting(xs: List[Int]): Unit =
    xs.foreach(x => List(x).foreach(y => if (y > 0) work()))

  def named_nested_function(a: Boolean): Unit = {
    def nested(): Unit = if (a) work()
    nested()
  }

  def class_in_method(a: Boolean): Int = {
    class LocalClass {
      def class_read(): Unit = if (a) work()
    }
    object LocalObject {
      def object_read(): Unit = if (a) work()
    }
    new LocalClass().class_read() + LocalObject.object_read()
  }

  def condition_nesting(a: Boolean, b: Boolean): Unit = {
    if (if (a) b else false) work()
  }

  def recursion_direct(n: Int): Unit =
    if (n > 0) recursion_direct(n - 1)

  def recursion_two_calls(n: Int): Unit =
    if (n > 0) {
      recursion_two_calls(n - 1)
      recursion_two_calls(n - 2)
    }

  def recursion_qualified_self(n: Int): Unit =
    if (n > 0) this.recursion_qualified_self(n - 1)

  def recursion_other_receiver(n: Int, other: Other): Unit =
    if (n > 0) other.recursion_other_receiver(n - 1, other)

  def recursion_overload_delegate(n: Int): Int = recursion_overload_delegate(n, 0)
  def recursion_overload_delegate(n: Int, depth: Int): Int = if (depth > 0) 1 else 0

  def recursion_in_closure(n: Int): Unit =
    List(1).foreach(_ => if (n > 0) recursion_in_closure(n - 1))

  def recursion_same_file_cycle_a(n: Int): Unit =
    if (n > 0) recursion_same_file_cycle_b(n - 1)

  def recursion_same_file_cycle_b(n: Int): Unit =
    if (n > 0) recursion_same_file_cycle_a(n - 1)

  def recursion_cross_file_zero(n: Int): Unit =
    // The peer is intentionally absent from this one-file fixture.
    if (n > 0) absentPeerFromAnotherFile(n - 1)

  def for_comprehension(xs: List[Int], ys: List[Int]): List[Int] =
    for {
      x <- xs if x > 0 && x < 8
      y <- ys if y != 0 || x > 0
    } yield x + y

  def get_words(number: Int): String = number match {
    case 1 => "one"
    case 2 => "a couple"
    case 3 => "a few"
    case _ => "lots"
  }

  private def work(): Unit = ()
  private def recover(): Unit = ()
  private def cleanup(): Unit = ()
}

class Other
