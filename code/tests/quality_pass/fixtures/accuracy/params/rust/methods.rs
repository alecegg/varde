pub struct Store {
    items: Vec<i32>,
}

impl Store {
    pub fn new() -> Self {
        Store { items: Vec::new() }
    }

    pub fn shared(&self) -> usize {
        self.items.len()
    }

    pub fn mutable(&mut self, value: i32) {
        self.items.push(value);
    }

    pub fn owned(self: Box<Self>) -> usize {
        self.items.len()
    }

    pub fn pair(&self, key: usize, fallback: i32) -> i32 {
        fallback
    }

    pub fn scale(&mut self, factor: i32, offset: i32, clamp: bool) -> i32 {
        factor + offset
    }
}

pub trait Load {
    fn load(&self, id: u32) -> i32;
}

pub struct Loader;

impl Load for Loader {
    fn load(&self, id: u32) -> i32 {
        id as i32
    }

    fn extra(&self, first: i32, second: i32) -> i32 {
        first + second
    }
}
