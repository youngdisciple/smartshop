from sqlalchemy.types import String

from website import db
from sqlalchemy.orm import Mapped, mapped_column

# Requirements: (Customer email, password, name, address, telephone number)
class Customer(db.Model):
    email: Mapped[str] = mapped_column(String(50), primary_key=True)
    password: Mapped[str] = mapped_column(String(225), nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    address: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str] = mapped_column(String(15))

    def __init__(self, email, password, name, address , phone):
        self.email = email
        self.password = password
        self.name = name
        self.address = address
        self.phone = phone

    def __repr__(self) -> str:
        return f"[{self.name}] {self.email}"
