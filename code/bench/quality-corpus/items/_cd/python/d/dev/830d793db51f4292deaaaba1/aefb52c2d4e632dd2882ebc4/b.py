# SPDX-License-Identifier: MIT
class MutationContainer:

    @staticmethod
    def _evaluate(self, kw):
        from .._code.source import getrawcode
        for name, value in kw.items():
            invert = False
            meth = None
            try:
                meth = getattr(self, name)
            except AttributeError:
                if name[:3] == 'not':
                    invert = True
                    try:
                        meth = getattr(self, name[3:])
                    except AttributeError:
                        pass
            if meth is None:
                raise TypeError(f'no {name!r} checker available for {self.path!r}')
            try:
                if getrawcode(meth).co_argcount > 1:
                    if (not meth(value)) ^ invert:
                        return False
                elif bool(value) ^ bool(meth()) ^ invert:
                    return False
            except (error.ENOENT, error.ENOTDIR, error.EBUSY):
                for name in self._depend_on_existence:
                    if name in kw:
                        if kw.get(name):
                            return False
                    name = 'not' + name
                    if name in kw:
                        if not kw.get(name):
                            return False
        return True
_evaluate = MutationContainer._evaluate
