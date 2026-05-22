from __future__ import annotations

from sqlalchemy import and_

from app.filters.contact_filters import InvalidFilterError


class FilterCompiler:
    def __init__(self, registry):
        self.registry = registry

    def compile(self, group):
        if group.logic != "AND":
            raise InvalidFilterError("Only AND filters are supported")

        conditions = []
        for expression in group.filters:
            compiler = self.registry.get(expression.field)
            if compiler is None:
                raise InvalidFilterError(f"Unsupported filter field: {expression.field}")
            conditions.append(compiler(expression))
        return and_(*conditions) if conditions else None

