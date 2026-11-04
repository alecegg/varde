pub fn zero() -> i32 {
    0
}

pub fn one(value: i32) -> i32 {
    value
}

pub fn two(a: i32, b: i32) -> i32 {
    a + b
}

pub fn borrow<'a, T>(value: &'a T) -> &'a T {
    value
}

pub fn generic<T>(value: T) -> T {
    value
}

pub fn slice(values: &[i32]) -> usize {
    values.len()
}

pub fn tuple((a, b): (i32, i32)) -> i32 {
    a + b
}

pub fn named(first: i32, second: i32, third: i32) -> i32 {
    first + second + third
}

pub fn fallback(value: Option<i32>, default: i32) -> i32 {
    value.unwrap_or(default)
}
