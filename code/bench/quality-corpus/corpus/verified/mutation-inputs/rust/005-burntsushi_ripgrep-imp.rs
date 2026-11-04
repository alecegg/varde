fn imp() -> bool {
    use std::{
        fs::File,
        os::{fd::AsFd, unix::fs::FileTypeExt},
    };

    let stdin = std::io::stdin();
    let fd = match stdin.as_fd().try_clone_to_owned() {
        Ok(fd) => fd,
        Err(err) => {
            log::debug!(
                "for heuristic stdin detection on Unix, \
                 could not clone stdin file descriptor \
                 (thus assuming stdin is not readable): {err}",
            );
            return false;
        }
    };
    let file = File::from(fd);
    let md = match file.metadata() {
        Ok(md) => md,
        Err(err) => {
            log::debug!(
                "for heuristic stdin detection on Unix, \
                 could not get file metadata for stdin \
                 (thus assuming stdin is not readable): {err}",
            );
            return false;
        }
    };
    let ft = md.file_type();
    let is_file = ft.is_file();
    let is_fifo = ft.is_fifo();
    let is_socket = ft.is_socket();
    let is_readable = is_file || is_fifo || is_socket;
    log::debug!(
        "for heuristic stdin detection on Unix, \
         found that \
         is_file={is_file}, is_fifo={is_fifo} and is_socket={is_socket}, \
         and thus concluded that is_stdin_readable={is_readable}",
    );
    is_readable
}
