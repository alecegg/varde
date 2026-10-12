fn main() -> std::process::ExitCode {
    varde::install_closed_stdout_hook();
    varde::router::main(std::env::args_os().collect(), &varde::io())
}
