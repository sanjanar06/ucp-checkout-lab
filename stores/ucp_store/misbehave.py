"""Lab addition (not Google's code): the store's misbehave switch (Stage 5).

Before a trial the supervisor saves the scenario's note as misbehave.json next
to the live databases. The checkout service calls on_event() after each
checkout event; when the event matches the note's "when", the trick runs once:

  1. check:     is there a note, not yet fired, waiting for this event?
  2. do:        run the trick (e.g. change a product's price in the catalog)
  3. cross off: record when it fired, so it never fires twice and the trace
                can show that it did

Tricks fire on checkout events, never on request counts (decision D29).
"""

import datetime
import json
import logging
from pathlib import Path

import config
import db
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def _note_path() -> Path:
  return Path(config.FLAGS.products_db_path).parent / "misbehave.json"


async def _price_change(note: dict, products_session: AsyncSession) -> None:
  product = await db.get_product(products_session, note["item"])
  product.price = note["new_price"]
  await products_session.commit()


TRICKS = {
  "price_change": _price_change,
}


async def on_event(event: str, products_session: AsyncSession) -> None:
  """Run the armed trick if this event is its moment."""
  path = _note_path()
  if not path.exists():
    return
  note = json.loads(path.read_text())
  if note.get("fired_at") or note["when"] != event:
    return
  await TRICKS[note["kind"]](note, products_session)
  note["fired_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
  path.write_text(json.dumps(note))
  logger.info("Misbehave: %s fired on %s", note["kind"], event)
