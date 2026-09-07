import json

from fastclm.services.contracts import ContractService
from fastclm.services.signatures import SignatureService


def test_signwell_stub_matches_create_document_shape(workspace):
    actor, _, _ = workspace
    contracts = ContractService()
    contract = contracts.create(actor, {"title": "Signature agreement"})
    contracts.transition(actor, contract["id"], "review")
    contracts.transition(actor, contract["id"], "approval")
    contracts.approve(actor, contract["id"], "approved")
    request = SignatureService().prepare(actor, contract["id"], "signwell", "Casey Smith", "casey@example.test")
    payload = json.loads(request["request_json"])
    assert payload["draft"] is True
    assert payload["recipients"][0]["id"] == "signer_1"
    assert payload["metadata"]["fastclm_contract_id"] == contract["id"]
    assert request["status"] == "configuration_required"
