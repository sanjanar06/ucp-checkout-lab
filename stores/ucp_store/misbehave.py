"""Lab addition (not Google's code): the store's misbehave switch (Stage 5).

Before a trial the supervisor saves the scenario's note as misbehave.json next
to the live databases. The checkout service calls on_event() after each
checkout event; when the event matches the note's "when", the trick runs once:

  1. check:     is there a note, not yet fired, waiting for this event?
  2. do:        run the trick (change a product's price, sell an item out,
                set how many are left, rewrite a product's title, or start
                needing the buyer)
  3. cross off: record when it fired, so it never fires twice and the trace
                can show that it did

Tricks fire on checkout events, never on request counts: AIs make different
numbers of requests, so counting would give each AI a different test.
"""

import datetime
import json
import logging
from pathlib import Path

import config
import db
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def _note_path() -> Path:
  return Path(config.FLAGS.products_db_path).parent / "misbehave.json"


async def _price_change(note: dict, products: AsyncSession, transactions: AsyncSession) -> None:
  product = await db.get_product(products, note["item"])
  product.price = note["new_price"]
  await products.commit()


async def _sell_out(note: dict, products: AsyncSession, transactions: AsyncSession) -> None:
  await transactions.execute(
    update(db.Inventory).where(db.Inventory.product_id == note["item"]).values(quantity=0)
  )
  await transactions.commit()


async def _set_stock(note: dict, products: AsyncSession, transactions: AsyncSession) -> None:
  # E.g. leave one unit, so another buyer can take the last one (Stage 6).
  await transactions.execute(
    update(db.Inventory).where(db.Inventory.product_id == note["item"])
    .values(quantity=note["quantity"])
  )
  await transactions.commit()


async def _rewrite_title(note: dict, products: AsyncSession, transactions: AsyncSession) -> None:
  # Trick text: an instruction hidden in product text, as an outside seller
  # on a marketplace could write it. Checkouts show titles from the catalog.
  product = await db.get_product(products, note["item"])
  product.title = note["title"]
  await products.commit()


async def _require_escalation(note: dict, products: AsyncSession, transactions: AsyncSession) -> None:
  # Nothing to change in the databases: once this note has fired, the
  # checkout service reports requires_escalation (see escalation()).
  pass


TRICKS = {
  "price_change": _price_change,
  "sell_out": _sell_out,
  "set_stock": _set_stock,
  "rewrite_title": _rewrite_title,
  "require_escalation": _require_escalation,
}


def escalation() -> dict | None:
  """The fired require_escalation note, or None: does the checkout need the buyer?"""
  path = _note_path()
  if not path.exists():
    return None
  note = json.loads(path.read_text())
  if note.get("kind") == "require_escalation" and note.get("fired_at"):
    return note
  return None


async def on_event(
  event: str, products_session: AsyncSession, transactions_session: AsyncSession
) -> None:
  """Run the armed trick if this event is its moment."""
  path = _note_path()
  if not path.exists():
    return
  note = json.loads(path.read_text())
  if note.get("fired_at") or note["when"] != event:
    return
  await TRICKS[note["kind"]](note, products_session, transactions_session)
  note["fired_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
  path.write_text(json.dumps(note))
  logger.info("Misbehave: %s fired on %s", note["kind"], event)
