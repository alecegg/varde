package calls

type Receiver struct{}
func (r Receiver) name(value int) {}
func alpha(values ...int) {}
func beta(value int) {}
func run() {
    alpha(1)
    alpha(2, 3)
    receiver := Receiver{}
    receiver.name(4)
    beta(5)
}
