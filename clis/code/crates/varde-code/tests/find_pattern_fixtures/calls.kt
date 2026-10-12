class Receiver { fun name(value: Int) {} }
fun alpha(vararg values: Int) {}
fun beta(value: Int) {}
fun run() {
    alpha(1)
    alpha(2, 3)
    val receiver = Receiver()
    receiver.name(4)
    beta(5)
}
