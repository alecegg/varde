def alpha(values: Int*): Unit = {}
def beta(value: Int): Unit = {}
object Calls {
  def main(args: Array[String]): Unit = {
    alpha(1)
    alpha(1, 2)
    objectRef.alpha(3)
    beta(4)
  }
}
