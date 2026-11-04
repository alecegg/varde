pub fn identity<T>(value: T) -> T {
    value
}

pub fn pair<K, V>(key: K, value: V) -> (K, V) {
    (key, value)
}

pub fn mapped<T, U>(values: Vec<T>, limit: usize) -> Vec<U> {
    Vec::new()
}

pub fn borrowed<'a, T: ?Sized>(value: &'a T) -> &'a T {
    value
}

pub fn zero<T>() -> T
where
    T: Default,
{
    T::default()
}

pub fn grouped<'a, T, U>(first: &'a T, second: U, third: usize) -> usize {
    third
}
