"""Online payment — not built yet; this is where it plugs in.

After a booking is saved, BookingFlow calls `request_deposit(booking)`. Today it
returns None, so the patient is told to pay at the clinic. To add payment:

  1. create the invoice here (QPay for Mongolia branches, Toss/KakaoPay for Korea;
     `booking["country"]`, `booking["price"]` and `booking["currency"]` say which)
  2. return the payment link: it is shown in the confirmation message and the
     booking gets payment_status = "pending"
  3. add a webhook in main.py that calls store.set_payment(id, "paid") when the
     provider confirms
"""
from typing import Optional

from .config import settings


def request_deposit(booking: dict) -> Optional[str]:
    """Payment link for this booking's deposit, or None when payment is off."""
    if not settings.PAYMENT_ENABLED:
        return None
    raise NotImplementedError("online payment is not built yet: see app/payment.py")
