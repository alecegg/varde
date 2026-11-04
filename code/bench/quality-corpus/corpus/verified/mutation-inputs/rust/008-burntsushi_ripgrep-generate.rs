pub(crate) fn generate() -> String {
    let mut opts = String::new();
    for flag in FLAGS.iter() {
        opts.push_str("--");
        opts.push_str(flag.name_long());
        opts.push(' ');
        if let Some(short) = flag.name_short() {
            opts.push('-');
            opts.push(char::from(short));
            opts.push(' ');
        }
        if let Some(name) = flag.name_negated() {
            opts.push_str("--");
            opts.push_str(name);
            opts.push(' ');
        }
    }
    opts.push_str("<PATTERN> <PATH>...");

    let mut cases = String::new();
    for flag in FLAGS.iter() {
        let template = if !flag.doc_choices().is_empty() {
            let choices = flag.doc_choices().join(" ");
            TEMPLATE_CASE_CHOICES.trim_end().replace("!CHOICES!", &choices)
        } else {
            TEMPLATE_CASE.trim_end().to_string()
        };
        let name = format!("--{}", flag.name_long());
        cases.push_str(&template.replace("!FLAG!", &name));
        if let Some(short) = flag.name_short() {
            let name = format!("-{}", char::from(short));
            cases.push_str(&template.replace("!FLAG!", &name));
        }
        if let Some(negated) = flag.name_negated() {
            let name = format!("--{negated}");
            cases.push_str(&template.replace("!FLAG!", &name));
        }
    }

    TEMPLATE_FULL
        .replace("!OPTS!", &opts)
        .replace("!CASES!", &cases)
        .trim_start()
        .to_string()
}
