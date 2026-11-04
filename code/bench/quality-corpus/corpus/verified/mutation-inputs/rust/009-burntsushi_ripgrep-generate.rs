pub(crate) fn generate() -> String {
    let mut flags = String::new();
    for (i, flag) in FLAGS.iter().enumerate() {
        let doc = flag.doc_short().replace("'", "''");

        let dash_name = format!("--{}", flag.name_long());
        let name = flag.name_long();
        if i > 0 {
            flags.push('\n');
        }
        flags.push_str("      ");
        flags.push_str(
            &TEMPLATE_FLAG
                .replace("!DASH_NAME!", &dash_name)
                .replace("!NAME!", &name)
                .replace("!DOC!", &doc),
        );

        if let Some(byte) = flag.name_short() {
            let dash_name = format!("-{}", char::from(byte));
            let name = char::from(byte).to_string();
            flags.push_str("\n      ");
            flags.push_str(
                &TEMPLATE_FLAG
                    .replace("!DASH_NAME!", &dash_name)
                    .replace("!NAME!", &name)
                    .replace("!DOC!", &doc),
            );
        }

        if let Some(negated) = flag.name_negated() {
            let dash_name = format!("--{negated}");
            flags.push_str("\n      ");
            flags.push_str(
                &TEMPLATE_FLAG
                    .replace("!DASH_NAME!", &dash_name)
                    .replace("!NAME!", &negated)
                    .replace("!DOC!", &doc),
            );
        }
    }
    TEMPLATE.trim_start().replace("!FLAGS!", &flags)
}
