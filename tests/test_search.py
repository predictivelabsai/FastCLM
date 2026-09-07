from fastclm.services.contracts import ContractService
from fastclm.services.identity import IdentityService


def test_full_text_search_covers_body_counterparty_prefix_and_tenant(workspace):
    actor, _, _ = workspace
    contracts = ContractService()
    counterparty = contracts.add_counterparty(actor, {"name": "Quasar Analytics Ltd"})
    body_match = contracts.create(actor, {"title": "Services terms", "counterparty_id": counterparty["id"]})
    contracts.add_block(actor, body_match["id"], "clause", "Sublicensing is prohibited without prior written consent.")
    title_match = contracts.create(actor, {"title": "Sublicensing framework"})

    results = contracts.list(actor, "sublicens")
    assert [item["id"] for item in results] == [title_match["id"], body_match["id"]]
    assert contracts.list(actor, "Quasar")[0]["id"] == body_match["id"]

    identity = IdentityService()
    user, organisation = identity.create_workspace("search-other@example.test", "Another-secure-password1!", "Other", "Other Search")
    other = identity.actor(user["id"], organisation["id"])
    contracts.create(other, {"title": "Sublicensing secret"})
    assert {item["id"] for item in contracts.list(actor, "sublicensing")} == {title_match["id"], body_match["id"]}
