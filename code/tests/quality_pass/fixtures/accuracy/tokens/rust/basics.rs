const MAX_RETRIES: usize = 3;
const DEFAULT_NAME: &str = "anonymous";

#[derive(Debug, Clone)]
pub struct Account {
    pub owner: String,
    pub balance: f64,
}

impl Account {
    pub fn deposit(&mut self, amount: f64) -> f64 {
        if amount <= 0.0 {
            panic!("bad amount: {}", amount);
        }
        self.balance += amount;
        self.balance
    }
}

pub fn total(accounts: &[Account]) -> f64 {
    let mut running = 0.0;
    for account in accounts {
        running += account.balance;
    }
    running
}

pub fn describe<'a>(account: &'a Account) -> &'a str {
    account.owner.as_str()
}
