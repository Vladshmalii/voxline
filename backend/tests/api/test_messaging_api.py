"""The messaging resource: what a configuration form is allowed to send.

``capabilities`` and ``options`` are NOT NULL columns, and a UI that renders
them as a group of inputs sends ``null`` when every input is blank — it has no
other way to say "none of these are set now". These tests pin that the API
reads that as ``{}`` rather than a 422 on create and a constraint violation on
update, because "leave all the extras empty" is the ordinary case, not an edge
one.
"""

from __future__ import annotations

from src.common.enums.engine import MessagingAdapterEnum

PAYLOAD = {
    "name": "mamonty",
    "adapter": MessagingAdapterEnum.mamonty.value,
    "is_active": True,
    "auth_token": "key",
    "sender": "VIRTA",
}


async def test_a_route_can_be_created_with_no_extras_at_all(client):
    response = await client.post(
        "/v1/messaging", json={**PAYLOAD, "capabilities": None, "options": None}
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["capabilities"] == {}
    assert body["options"] == {}


async def test_clearing_the_extras_empties_them_instead_of_failing(client):
    created = await client.post(
        "/v1/messaging",
        json={**PAYLOAD, "options": {"channel": "char", "timeout": 30}},
    )
    assert created.status_code == 201, created.text
    route_id = created.json()["id"]

    cleared = await client.patch(f"/v1/messaging/{route_id}", json={"options": None})

    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["options"] == {}


async def test_an_untouched_section_is_left_alone_by_a_partial_update(client):
    """Absent is not the same as null — that is what makes PATCH partial."""
    created = await client.post(
        "/v1/messaging", json={**PAYLOAD, "options": {"channel": "digit"}}
    )
    route_id = created.json()["id"]

    renamed = await client.patch(f"/v1/messaging/{route_id}", json={"name": "renamed"})

    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["options"] == {"channel": "digit"}
