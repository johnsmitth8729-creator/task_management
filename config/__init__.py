# Python 3.14 + Django 6.1 BaseContext.__copy__ compatibility patch
try:
    from django.template.context import BaseContext

    def _base_context_copy(self):
        duplicate = object.__new__(self.__class__)
        duplicate.dicts = self.dicts[:]
        return duplicate

    BaseContext.__copy__ = _base_context_copy
except Exception:
    pass
