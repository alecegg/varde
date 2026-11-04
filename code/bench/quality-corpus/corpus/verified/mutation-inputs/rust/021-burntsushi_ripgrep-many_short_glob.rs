fn many_short_glob(b: &mut test::Bencher) {
    let pats: Vec<_> = MANY_SHORT_GLOBS.iter().map(|&s| new_glob(s)).collect();
    b.iter(|| {
        let mut count = 0;
        for pat in &pats {
            if pat.matches(MANY_SHORT_SEARCH) {
                count += 1;
            }
        }
        assert_eq!(2, count);
    })
}
