class Receiver { func name(_ value: Int) {} }
func alpha(_ values: Int...) {}
func beta(_ value: Int) {}
func run() {
    alpha(1)
    alpha(2, 3)
    let receiver = Receiver()
    receiver.name(4)
    beta(5)
}
