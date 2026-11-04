def _geterrnoclass(self, eno: int) -> type[Error]:
    try:
        return self._errno2class[eno]
    except KeyError:
        clsname = errno.errorcode.get(eno, f"UnknownErrno{eno}")
        errorcls = type(
            clsname,
            (Error,),
            {"__module__": "py.error", "__doc__": os.strerror(eno)},
        )
        self._errno2class[eno] = errorcls
        return errorcls
