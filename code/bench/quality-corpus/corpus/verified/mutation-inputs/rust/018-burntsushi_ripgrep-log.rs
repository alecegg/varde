fn log(&self, record: &log::Record<'_>) {
    match (record.file(), record.line()) {
        (Some(file), Some(line)) => {
            eprintln_locked!(
                "{}|{}|{}:{}: {}",
                record.level(),
                record.target(),
                file,
                line,
                record.args()
            );
        }
        (Some(file), None) => {
            eprintln_locked!(
                "{}|{}|{}: {}",
                record.level(),
                record.target(),
                file,
                record.args()
            );
        }
        _ => {
            eprintln_locked!(
                "{}|{}: {}",
                record.level(),
                record.target(),
                record.args()
            );
        }
    }
}
