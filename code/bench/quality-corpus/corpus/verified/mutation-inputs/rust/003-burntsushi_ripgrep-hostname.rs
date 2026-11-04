pub fn hostname() -> io::Result<OsString> {
    #[cfg(windows)]
    {
        use winapi_util::sysinfo::{ComputerNameKind, get_computer_name};
        get_computer_name(ComputerNameKind::PhysicalDnsHostname)
    }
    #[cfg(unix)]
    {
        gethostname()
    }
    #[cfg(not(any(windows, unix)))]
    {
        Err(io::Error::new(
            io::ErrorKind::Other,
            "hostname could not be found on unsupported platform",
        ))
    }
}
