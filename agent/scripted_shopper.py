"""A non-AI shopper that follows fixed steps: the same ones you typed by hand.

It exists to prove the lab works before any AI is involved. Given a
scenario's [instruction.details], it:

  1. reads the store's info card
  2. creates a checkout (items, buyer, discount codes)
  3. adds the shipping address
  4. picks the shipping option
  5. stops at ready_for_complete and asks the buyer
  6. completes if the buyer approves, cancels if not
     (and cancels if the checkout never becomes ready)

`bug` makes it misbehave on purpose, so we can check the grader catches it:
  ignore_decline  completes even when the buyer says no
  skip_cancel     stops without cancelling when the buyer says no
  wrong_quantity  orders one more of the first item than asked
"""

BUGS = ("ignore_decline", "skip_cancel", "wrong_quantity")

# The store's pretend card that always succeeds (stores/seed/*/payment_instruments.csv).
TEST_CARD = {
    "id": "instr_1",
    "handler_id": "mock_payment_handler",
    "type": "card",
    "credential": {"type": "token", "token": "success_token"},
    "display": {"brand": "Visa", "last_digits": "1234"},
}


def run(client, details, buyer_approves, bug=None):
    """Run one trial. Returns a short log of what the shopper did and why."""
    log = []
    items = [dict(i) for i in details["items"]]
    if bug == "wrong_quantity":
        items[0]["quantity"] += 1
    codes = details.get("discount_codes", [])

    client.discover()

    # 2. Create the checkout.
    body = {
        "line_items": [{"item": {"id": i["id"]}, "quantity": i["quantity"]} for i in items],
        "buyer": details["buyer"],
        "currency": "USD",
        "payment": {"instruments": [], "handlers": []},
    }
    if codes:
        body["discounts"] = {"codes": codes}
    status, checkout = client.create_checkout(body)
    if status >= 400 or not checkout.get("id"):
        log.append(f"create failed ({status}); stopping")
        return log
    checkout_id = checkout["id"]
    log.append(f"created checkout, status {checkout.get('status')}")

    # Every update resends the line items, now with the ids the store gave them.
    def base():
        b = {
            "id": checkout_id,
            "line_items": [
                {"id": li["id"], "item": {"id": li["item"]["id"]}, "quantity": li["quantity"]}
                for li in checkout["line_items"]
            ],
            "currency": "USD",
            "payment": {"instruments": [], "handlers": []},
        }
        if codes:
            b["discounts"] = {"codes": codes}
        return b

    line_item_ids = [li["id"] for li in checkout["line_items"]]
    method = {
        "id": "method_1",
        "type": "shipping",
        "line_item_ids": line_item_ids,
        "destinations": [{"id": "dest_1", **details["ship_to"]}],
        "selected_destination_id": "dest_1",
    }

    # 3. Add the address.
    status, reply = client.update_checkout(
        checkout_id, {**base(), "fulfillment": {"methods": [method]}}, step="set_address"
    )
    if status < 400:
        checkout = reply

    # 4. Pick the shipping option.
    method["groups"] = [
        {"id": "group_1", "line_item_ids": line_item_ids,
         "selected_option_id": details["shipping_option"]}
    ]
    status, reply = client.update_checkout(
        checkout_id, {**base(), "fulfillment": {"methods": [method]}}, step="set_shipping"
    )
    if status < 400:
        checkout = reply
    log.append(f"after shipping, status {checkout.get('status')}")

    # 5. Never go past ready_for_complete without the buyer.
    if checkout.get("status") != "ready_for_complete":
        log.append("checkout never became ready; cancelling")
        client.cancel_checkout(checkout_id)
        return log

    total = next((t["amount"] for t in checkout.get("totals", []) if t["type"] == "total"), None)
    log.append(f"asked buyer to approve total {total}; buyer says {'yes' if buyer_approves else 'no'}")

    # 6. Act on the buyer's answer.
    if buyer_approves or bug == "ignore_decline":
        status, reply = client.complete_checkout(checkout_id, {"payment": {"instruments": [TEST_CARD]}})
        log.append(f"completed ({status}), status {(reply or {}).get('status')}")
    elif bug == "skip_cancel":
        log.append("buyer declined; stopping without cancelling")
    else:
        client.cancel_checkout(checkout_id)
        log.append("buyer declined; cancelled")
    return log
