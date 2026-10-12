"""Login, refresh, logout, permissions, organization switching, admin API."""

from __future__ import annotations

from tests import support  # isort: skip

from sqlalchemy import select

from src.core.control.models import RefreshToken
from src.core.db.session import SessionMaker
from src.settings import SETTINGS
from tests.auth.conftest import PASSWORD, expired_access_token, login, replace_cookie

# -- login / me ------------------------------------------------------------------


async def test_login_sets_cookies_and_returns_session(client, world):
    org = await world.org("Acme")
    user = await world.user("a@x.io", memberships={org: "owner"})

    r = await login(client, "A@X.io")  # e-mail is case-insensitive
    assert r.status_code == 200, r.text
    assert r.json() == {
        "user": {
            "id": user.id,
            "email": "a@x.io",
            "name": "a",
            "is_superuser": False,
        },
        "organization": {"uuid": str(org.uuid), "name": "Acme"},
        "role": "owner",
    }
    set_cookie = r.headers.get_list("set-cookie")
    names = {c.split("=", 1)[0] for c in set_cookie}
    assert names == {"access_token", "refresh_token"}
    assert all("httponly" in c.lower() for c in set_cookie)

    me = await client.get("/v1/auth/me")
    assert me.status_code == 200 and me.json()["role"] == "owner"
    assert me.json()["user"]["email"] == "a@x.io"


async def test_login_rejects_bad_credentials(client, world):
    org = await world.org()
    await world.user("a@x.io", memberships={org: "staff"})
    await world.user("off@x.io", memberships={org: "staff"}, active=False)

    for email, password in (
        ("a@x.io", "wrong-password"),
        ("nobody@x.io", PASSWORD),
        ("off@x.io", PASSWORD),
    ):
        r = await client.post(
            "/v1/auth/login", json={"email": email, "password": password}
        )
        assert r.status_code == 401
        assert r.json()["detail"] == "invalid_credentials"
    assert "access_token" not in client.cookies


async def test_login_without_any_organization_is_forbidden(client, world):
    await world.user("lonely@x.io")
    r = await login(client, "lonely@x.io")
    assert r.status_code == 403 and r.json()["detail"] == "no_organization"


async def test_protected_routes_require_a_session(client):
    r = await client.get("/v1/auth/me")
    assert r.status_code == 401 and r.json()["detail"] == "unauthorized"
    r = await client.get("/v1/auth/me")
    assert r.status_code == 401


# -- refresh ---------------------------------------------------------------------


async def test_expired_access_token_then_refresh(client, world):
    org = await world.org()
    user = await world.user("a@x.io", memberships={org: "staff"})
    assert (await login(client, "a@x.io")).status_code == 200
    old_refresh = client.cookies["refresh_token"]

    replace_cookie(
        client, "access_token", expired_access_token(user.id, str(org.uuid))
    )
    r = await client.get("/v1/auth/me")
    assert r.status_code == 401 and r.json()["detail"] == "token_expired"

    r = await client.post("/v1/auth/refresh")
    assert r.status_code == 200 and r.json()["role"] == "staff"
    assert client.cookies["refresh_token"] != old_refresh
    assert (await client.get("/v1/auth/me")).status_code == 200


async def test_refresh_token_is_single_use_and_replay_revokes_all(
    client, new_client, world
):
    org = await world.org()
    await world.user("a@x.io", memberships={org: "staff"})
    await login(client, "a@x.io")
    stolen = client.cookies["refresh_token"]

    assert (await client.post("/v1/auth/refresh")).status_code == 200
    current = client.cookies["refresh_token"]

    attacker = new_client()
    attacker.cookies.set("refresh_token", stolen)
    r = await attacker.post("/v1/auth/refresh")
    assert r.status_code == 401 and r.json()["detail"] == "unauthorized"

    # Replay burned the whole family, including the legitimate successor.
    legit = new_client()
    legit.cookies.set("refresh_token", current)
    assert (await legit.post("/v1/auth/refresh")).status_code == 401


async def test_refresh_without_cookie(client):
    r = await client.post("/v1/auth/refresh")
    assert r.status_code == 401 and r.json()["detail"] == "unauthorized"


async def test_missing_access_cookie_with_refresh_cookie_asks_to_refresh(
    client, world
):
    org = await world.org()
    await world.user("a@x.io", memberships={org: "staff"})
    await login(client, "a@x.io")
    del client.cookies["access_token"]
    r = await client.get("/v1/auth/me")
    assert r.status_code == 401 and r.json()["detail"] == "token_expired"
    assert (await client.post("/v1/auth/refresh")).status_code == 200
    assert (await client.get("/v1/auth/me")).status_code == 200


async def test_logout_revokes_refresh_token(client, world):
    org = await world.org()
    await world.user("a@x.io", memberships={org: "staff"})
    await login(client, "a@x.io")
    refresh = client.cookies["refresh_token"]

    r = await client.post("/v1/auth/logout")
    assert r.status_code == 204
    assert not client.cookies.get("access_token")

    client.cookies.set("refresh_token", refresh)
    assert (await client.post("/v1/auth/refresh")).status_code == 401
    async with SessionMaker.get_control_session()() as session:
        rows = (await session.execute(select(RefreshToken))).scalars().all()
    assert rows and all(row.revoked_at is not None for row in rows)


# -- permissions -------------------------------------------------------------------


async def test_role_gates(client, new_client, world):
    org = await world.org()
    await world.user("viewer@x.io", memberships={org: "viewer"})
    await world.user("admin@x.io", memberships={org: "admin"})

    await login(client, "viewer@x.io")
    assert (await client.get("/v1/auth/me")).json()["role"] == "viewer"
    # admin_only tenant route and account admin: both closed to a viewer.
    assert (await client.get("/v1/telephony")).status_code == 403
    assert (await client.get("/v1/admin/users")).status_code == 403

    admin = new_client()
    await login(admin, "admin@x.io")
    assert (await admin.get("/v1/admin/users")).status_code == 200


async def test_superuser_is_super_admin_everywhere(client, world):
    org1 = await world.org("One")
    org2 = await world.org("Two")
    await world.user("root@x.io", superuser=True)

    r = await login(client, "root@x.io")
    assert r.status_code == 200 and r.json()["role"] == "super_admin"
    assert r.json()["organization"]["uuid"] == str(org1.uuid)

    orgs = (await client.get("/v1/organizations")).json()
    assert [(o["uuid"], o["role"]) for o in orgs] == [
        (str(org1.uuid), "super_admin"),
        (str(org2.uuid), "super_admin"),
    ]
    r = await client.post(f"/v1/auth/change_organization/{org2.uuid}")
    assert r.status_code == 200 and r.json()["organization"]["name"] == "Two"


async def test_user_removed_from_org_loses_access_immediately(
    client, new_client, world
):
    org = await world.org()
    staff = await world.user("staff@x.io", memberships={org: "staff"})
    await world.user("admin@x.io", memberships={org: "admin"})
    await login(client, "staff@x.io")
    assert (await client.get("/v1/auth/me")).status_code == 200  # warms the cache

    admin = new_client()
    await login(admin, "admin@x.io")
    r = await admin.delete(f"/v1/admin/organizations/{org.uuid}/members/{staff.id}")
    assert r.status_code == 204
    assert (await client.get("/v1/auth/me")).status_code == 403
    assert (await client.post("/v1/auth/refresh")).status_code == 401


async def test_role_change_is_visible_after_cache_invalidation(
    client, new_client, world
):
    org = await world.org()
    staff = await world.user("staff@x.io", memberships={org: "staff"})
    await world.user("admin@x.io", memberships={org: "admin"})
    await login(client, "staff@x.io")
    assert (await client.get("/v1/auth/me")).json()["role"] == "staff"

    admin = new_client()
    await login(admin, "admin@x.io")
    r = await admin.put(
        f"/v1/admin/organizations/{org.uuid}/members/{staff.id}",
        json={"role": "viewer"},
    )
    assert r.status_code == 200 and r.json()["role"] == "viewer"
    assert (await client.get("/v1/auth/me")).json()["role"] == "viewer"


# -- organization switching ----------------------------------------------------------


async def test_list_and_switch_organizations(client, world):
    a = await world.org("Alpha")
    b = await world.org("Beta")
    c = await world.org("Gamma")
    await world.user("u@x.io", memberships={a: "viewer", b: "owner"})

    r = await login(client, "u@x.io")
    assert r.json()["organization"]["name"] == "Alpha"  # first membership

    listed = (await client.get("/v1/organizations")).json()
    assert listed == [
        {"uuid": str(a.uuid), "name": "Alpha", "role": "viewer"},
        {"uuid": str(b.uuid), "name": "Beta", "role": "owner"},
    ]

    r = await client.post(f"/v1/auth/change_organization/{b.uuid}")
    assert r.status_code == 200
    assert r.json()["organization"]["uuid"] == str(b.uuid)
    assert r.json()["role"] == "owner"

    r = await client.post(f"/v1/auth/change_organization/{c.uuid}")
    assert r.status_code == 403
    # still in Beta
    assert (await client.get("/v1/auth/me")).json()["organization"]["name"] == "Beta"


async def test_login_into_a_chosen_organization(client, world):
    a = await world.org("Alpha")
    b = await world.org("Beta")
    await world.user("u@x.io", memberships={a: "viewer", b: "staff"})
    r = await login(client, "u@x.io", organization_uuid=str(b.uuid))
    assert r.json()["organization"]["name"] == "Beta" and r.json()["role"] == "staff"

    other = await world.org("Elsewhere")
    r = await login(client, "u@x.io", organization_uuid=str(other.uuid))
    assert r.status_code == 403


# -- admin API -----------------------------------------------------------------------


async def test_org_admin_manages_users_in_own_org_only(client, world):
    mine = await world.org("Mine")
    theirs = await world.org("Theirs")
    await world.user("admin@x.io", memberships={mine: "admin"})
    outsider = await world.user("out@x.io", memberships={theirs: "staff"})
    await login(client, "admin@x.io")

    r = await client.post(
        "/v1/admin/users",
        json={"email": "New@X.io", "name": "New", "password": "long-enough-pw"},
    )
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["email"] == "new@x.io"
    assert created["memberships"] == [
        {"organization_uuid": str(mine.uuid), "organization_name": "Mine", "role": "staff"}
    ]

    # cannot mint superusers, super_admins, or reach into another org
    assert (
        await client.post(
            "/v1/admin/users",
            json={"email": "s@x.io", "password": "long-enough-pw", "is_superuser": True},
        )
    ).status_code == 403
    assert (
        await client.post(
            "/v1/admin/users",
            json={"email": "s@x.io", "password": "long-enough-pw", "role": "super_admin"},
        )
    ).status_code == 403
    assert (
        await client.post(
            "/v1/admin/users",
            json={
                "email": "s@x.io",
                "password": "long-enough-pw",
                "organization_uuid": str(theirs.uuid),
            },
        )
    ).status_code == 403
    assert (
        await client.patch(f"/v1/admin/users/{outsider.id}", json={"name": "x"})
    ).status_code == 403

    listed = (await client.get("/v1/admin/users")).json()
    assert {u["email"] for u in listed} == {"admin@x.io", "new@x.io"}

    r = await client.patch(f"/v1/admin/users/{created['id']}", json={"name": "Renamed"})
    assert r.status_code == 200 and r.json()["name"] == "Renamed"

    dup = await client.post(
        "/v1/admin/users",
        json={"email": "new@x.io", "password": "long-enough-pw"},
    )
    assert dup.status_code == 409 and dup.json()["detail"] == "email_taken"


async def test_deactivated_user_is_locked_out(client, new_client, world):
    org = await world.org()
    staff = await world.user("staff@x.io", memberships={org: "staff"})
    await world.user("admin@x.io", memberships={org: "admin"})
    await login(client, "staff@x.io")
    assert (await client.get("/v1/auth/me")).status_code == 200

    admin = new_client()
    await login(admin, "admin@x.io")
    r = await admin.patch(f"/v1/admin/users/{staff.id}", json={"is_active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False

    assert (await client.get("/v1/auth/me")).status_code in (401, 403)
    assert (await client.post("/v1/auth/refresh")).status_code == 401
    assert (await login(client, "staff@x.io")).status_code == 401


async def test_password_change_revokes_sessions(client, new_client, world):
    org = await world.org()
    staff = await world.user("staff@x.io", memberships={org: "staff"})
    await world.user("admin@x.io", memberships={org: "admin"})
    await login(client, "staff@x.io")

    admin = new_client()
    await login(admin, "admin@x.io")
    r = await admin.patch(
        f"/v1/admin/users/{staff.id}", json={"password": "brand-new-password"}
    )
    assert r.status_code == 200
    assert (await client.post("/v1/auth/refresh")).status_code == 401
    r = await client.post(
        "/v1/auth/login", json={"email": "staff@x.io", "password": "brand-new-password"}
    )
    assert r.status_code == 200


async def test_only_superuser_creates_organizations_with_tenant_database(
    client, new_client, world
):
    org = await world.org()
    await world.user("admin@x.io", memberships={org: "admin"})
    await world.user("root@x.io", superuser=True)

    admin = new_client()
    await login(admin, "admin@x.io")
    r = await admin.post("/v1/admin/organizations", json={"name": "Nope"})
    assert r.status_code == 403
    listed = (await admin.get("/v1/admin/organizations")).json()
    assert len(listed) == 1

    await login(client, "root@x.io")
    r = await client.post("/v1/admin/organizations", json={"name": "Fresh"})
    assert r.status_code == 201, r.text
    new_uuid = r.json()["uuid"]
    db_name = f"{SETTINGS.db.prefix}{new_uuid}"
    try:
        assert support.database_exists(db_name)
        names = [o["name"] for o in (await client.get("/v1/admin/organizations")).json()]
        assert "Fresh" in names
    finally:
        support.drop_database(db_name)


async def test_membership_put_adds_user_to_org(client, world):
    a = await world.org("Alpha")
    b = await world.org("Beta")
    await world.user("admin@x.io", memberships={a: "admin", b: "admin"})
    user = await world.user("u@x.io", memberships={a: "viewer"})
    await login(client, "admin@x.io")

    r = await client.put(
        f"/v1/admin/organizations/{b.uuid}/members/{user.id}", json={"role": "staff"}
    )
    assert r.status_code == 200
    r = await client.put(
        f"/v1/admin/organizations/{b.uuid}/members/{user.id}", json={"role": "wizard"}
    )
    assert r.status_code == 400 and r.json()["detail"] == "invalid_role"
    r = await client.put(
        f"/v1/admin/organizations/{b.uuid}/members/999", json={"role": "staff"}
    )
    assert r.status_code == 404
