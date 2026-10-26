"""The pretend human buyer, and their saved card.

Any shopper (scripted or AI) asks for approval through Buyer.ask(). The answer
comes from the scenario's buyer_approves line. Each question is written into
the same timeline as the store requests, so the grader can check that no
checkout was completed before the buyer said yes.
"""

# The buyer's saved card: the store's test token that always succeeds
# (stores/seed/*/payment_instruments.csv). It is attached to "complete" by the
# buyer's wallet, so the AI never handles card details itself.
WALLET_CARD = {
    "id": "instr_1",
    "handler_id": "mock_payment_handler",
    "type": "card",
    "credential": {"type": "token", "token": "success_token"},
    "display": {"brand": "Visa", "last_digits": "1234"},
}


class Buyer:
    def __init__(self, approves, timeline):
        self.approves = approves
        self.timeline = timeline   # the UcpClient's transcript list

    def ask(self, message):
        self.timeline.append(
            {"step": "ask_buyer", "request": {"message": message},
             "response": {"approved": self.approves}}
        )
        return self.approves
