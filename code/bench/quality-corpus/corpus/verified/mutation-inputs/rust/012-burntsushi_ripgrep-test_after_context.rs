fn test_after_context() {
    let mkctx = |lines| {
        let mut mode = ContextMode::default();
        mode.set_after(lines);
        mode
    };

    let args = parse_low_raw(None::<&str>).unwrap();
    assert_eq!(ContextMode::default(), args.context);

    let args = parse_low_raw(["--after-context", "5"]).unwrap();
    assert_eq!(mkctx(5), args.context);

    let args = parse_low_raw(["--after-context=5"]).unwrap();
    assert_eq!(mkctx(5), args.context);

    let args = parse_low_raw(["-A", "5"]).unwrap();
    assert_eq!(mkctx(5), args.context);

    let args = parse_low_raw(["-A5"]).unwrap();
    assert_eq!(mkctx(5), args.context);

    let args = parse_low_raw(["-A5", "-A10"]).unwrap();
    assert_eq!(mkctx(10), args.context);

    let args = parse_low_raw(["-A5", "-A0"]).unwrap();
    assert_eq!(mkctx(0), args.context);

    let args = parse_low_raw(["-A5", "--passthru"]).unwrap();
    assert_eq!(ContextMode::Passthru, args.context);

    let args = parse_low_raw(["--passthru", "-A5"]).unwrap();
    assert_eq!(mkctx(5), args.context);

    let n = usize::MAX.to_string();
    let args = parse_low_raw(["--after-context", n.as_str()]).unwrap();
    assert_eq!(mkctx(usize::MAX), args.context);

    #[cfg(target_pointer_width = "64")]
    {
        let n = (u128::from(u64::MAX) + 1).to_string();
        let result = parse_low_raw(["--after-context", n.as_str()]);
        assert!(result.is_err(), "{result:?}");
    }
}
