def _format_repr_exception(exc: BaseException, obj: object) -> str:
    try:
        exc_info = _try_repr_or_str(exc)
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as inner_exc:
        exc_info = f"unpresentable exception ({_try_repr_or_str(inner_exc)})"
    return (
        f"<[{exc_info} raised in repr()] {type(obj).__name__} object at 0x{id(obj):x}>"
    )
