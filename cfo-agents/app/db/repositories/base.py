from __future__ import annotations

from typing import Generic, Iterable, Type, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Base

T = TypeVar("T", bound=Base)


class BaseRepository(Generic[T]):
    model: Type[T]

    def __init__(self, session: Session):
        self.session = session

    def add(self, obj: T) -> T:
        self.session.add(obj)
        self.session.flush()
        return obj

    def add_many(self, objs: Iterable[T]) -> None:
        self.session.add_all(list(objs))
        self.session.flush()

    def get(self, id: str) -> T | None:
        return self.session.get(self.model, id)

    def list(self, **filters) -> list[T]:
        stmt = select(self.model)
        for k, v in filters.items():
            stmt = stmt.where(getattr(self.model, k) == v)
        return list(self.session.execute(stmt).scalars())
