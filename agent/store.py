"""A small mock of a coffee chain's ordering backend: menu, stores, members with a saved usual,
and orders. Everything here is SAMPLE DATA made up for the demo. Prices, drink names, stores and
customers are illustrative and are not any real company's data."""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

MENU = {  # sample menu, price in cents by size
    "house_blend": {"name": "House Blend", "prices": {"small": 525, "medium": 575, "large": 625}},
    "dark_roast": {"name": "Dark Roast", "prices": {"small": 525, "medium": 575, "large": 625}},
    "iced_mint": {"name": "Iced Mint Coffee", "prices": {"small": 595, "medium": 650, "large": 710}},
    "cold_brew": {"name": "Cold Brew", "prices": {"small": 550, "medium": 600, "large": 650}},
    "croissant": {"name": "Butter Croissant", "prices": {"one": 450}},
}

STORES = {
    "mission": {"name": "Mission St", "open": True},
    "soma": {"name": "SoMa", "open": True},
    "oakland": {"name": "Oakland Uptown", "open": False},  # closed for the store-closed case
}

ORDER_CAP_CENTS = 3000  # pilot rule: anything over $30 goes to a person


@dataclass
class Member:
    phone: str
    first_name: str
    store: str
    usual: list[dict]          # saved cart
    opted_out: bool = False


@dataclass
class Order:
    id: str
    phone: str
    store: str
    items: list[dict]
    total_cents: int
    status: str = "awaiting_payment"   # awaiting_payment -> paid -> in_progress -> ready -> picked_up
    payment_request_id: str | None = None


@dataclass
class Store:
    members: dict[str, Member] = field(default_factory=dict)
    orders: dict[str, Order] = field(default_factory=dict)
    next_id: int = 1001
    kitchen_tickets: list = field(default_factory=list)

    @classmethod
    def sample(cls) -> "Store":
        s = cls()
        for m in [
            Member("+14155550101", "Maya", "mission",
                   [{"sku": "house_blend", "size": "large", "cream": "medium", "sweet": "light"}]),
            Member("+14155550102", "Dev", "soma",
                   [{"sku": "iced_mint", "size": "medium", "cream": "light", "sweet": "medium"},
                    {"sku": "croissant", "size": "one"}]),
            Member("+14155550103", "Ana", "oakland",
                   [{"sku": "dark_roast", "size": "small", "cream": "none", "sweet": "none"}]),
            Member("+14155550104", "Sam", "mission",
                   [{"sku": "cold_brew", "size": "large", "cream": "none", "sweet": "none"}] * 6),
        ]:
            s.members[m.phone] = m
        return s

    def clone(self) -> "Store":
        return copy.deepcopy(self)

    @staticmethod
    def price(items: list[dict]) -> int:
        return sum(MENU[i["sku"]]["prices"][i["size"]] for i in items)

    @staticmethod
    def describe(items: list[dict]) -> str:
        parts = []
        for i in items:
            name = MENU[i["sku"]]["name"]
            if i["size"] == "one":
                parts.append(name)
                continue
            extras = []
            if i.get("cream") and i["cream"] != "none":
                extras.append(f"{i['cream']} cream")
            if i.get("sweet") and i["sweet"] != "none":
                extras.append(f"{i['sweet']} sweet")
            if not extras:
                extras.append("black")
            parts.append(f"{i['size']} {name} ({', '.join(extras)})")
        return "; ".join(parts)

    def create_order(self, phone: str, items: list[dict], store: str) -> Order:
        o = Order(id=f"A{self.next_id}", phone=phone, store=store,
                  items=copy.deepcopy(items), total_cents=self.price(items))
        self.next_id += 1
        self.orders[o.id] = o
        return o

    def latest_order(self, phone: str) -> Order | None:
        mine = [o for o in self.orders.values() if o.phone == phone]
        return mine[-1] if mine else None

    def send_to_kitchen(self, order: Order) -> None:
        self.kitchen_tickets.append(order.id)
