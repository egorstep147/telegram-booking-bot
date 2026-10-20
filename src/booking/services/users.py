from sqlalchemy.dialects.postgresql import insert

from booking.db import AsyncSession
from booking.db.models import User


async def upsert(
    s: AsyncSession, user_id: int, first_name: str = "", username: str | None = None, phone: str | None = None
) -> None:
    """Запомнить клиента. Обновляем только переданное: запись с одним телефоном не сотрёт имя."""
    values = {"first_name": first_name, "username": username, "phone": phone}
    changed = {k: v for k, v in values.items() if v} | {"blocked": False}
    stmt = insert(User).values(id=user_id, **(values | {"first_name": first_name or ""}))
    await s.execute(stmt.on_conflict_do_update(index_elements=[User.id], set_=changed))
