package fixtures

import "fmt"

const MaxRetries = 3
const defaultName = "anonymous"

type Account struct {
	Owner   string
	Balance float64
}

func Total(accounts []Account) float64 {
	running := 0.0
	for _, account := range accounts {
		running += account.Balance
	}
	return running
}

func Describe(account Account) string {
	return fmt.Sprintf("%s: %.2f", account.Owner, account.Balance)
}
