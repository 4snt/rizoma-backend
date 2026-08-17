"""Testes do módulo de identidade.

O teste que mais importa aqui é `test_isolamento_entre_organizacoes`: ele prova
que um JWT válido da Org A, apontando explicitamente para a Org B via header,
não enxerga nada. É o cenário do atacante — não um caso de borda.
"""
import pytest
from sqlalchemy import text

from app.core.security import create_access_token
from app.modules.identity.oauth import GoogleOAuthProvider, OAuthClaims
from tests.mvp.conftest import (
    PREFIX,
    make_invitation,
    make_member,
    make_org,
    make_user,
    rand_email,
    rand_slug,
)


def auth(user_id, role: str = "org_admin", org_id=None) -> dict:
    headers = {"Authorization": f"Bearer {create_access_token(str(user_id), role)}"}
    if org_id is not None:
        headers["X-Organization"] = str(org_id)
    return headers


def fake_google(monkeypatch, email: str, name: str = "Fulano") -> None:
    """Monkeypatcha o adapter (GoogleOAuthProvider.verify), não uma função
    solta — é o ponto de injeção real desde a refatoração pra DI (oauth.py).
    Qualquer instância de GoogleOAuthProvider passa a devolver isto,
    inclusive a que get_oauth_provider() cria pra cada request."""

    async def _verify(self, access_token: str) -> OAuthClaims:
        return OAuthClaims(
            sub=f"google-{email}",
            email=email,
            name=name,
            avatar_url="https://example.test/a.png",
            email_verified=True,
        )

    monkeypatch.setattr(GoogleOAuthProvider, "verify", _verify)


# ── Organizações e /me ──────────────────────────────────────────────────────


async def test_criar_organizacao_e_ler_me(client, db):
    """A primeira org nasce de um usuário sem nenhum vínculo."""
    user_id = await make_user(db)
    slug = rand_slug()

    r = await client.post(
        f"{PREFIX}/organizations",
        json={"slug": slug, "name": "Laboratório Rizoma"},
        headers=auth(user_id),
    )
    assert r.status_code == 201, r.text
    org = r.json()
    assert org["slug"] == slug
    assert org["role"] == "org_admin"

    r = await client.get(f"{PREFIX}/me", headers=auth(user_id, org_id=org["id"]))
    assert r.status_code == 200, r.text
    me = r.json()
    assert me["user"]["id"] == str(user_id)
    assert me["role"] == "org_admin"
    assert me["organization"]["id"] == org["id"]
    assert [o["id"] for o in me["organizations"]] == [org["id"]]


async def test_me_sem_organizacao_da_403(client, db):
    user_id = await make_user(db)
    r = await client.get(f"{PREFIX}/me", headers=auth(user_id))
    assert r.status_code == 403


async def test_listar_organizacoes_do_usuario(client, db):
    user_id = await make_user(db)
    org_id = await make_org(db)
    await make_member(db, org_id, user_id, "coordinator")
    # Org de outra pessoa: não pode aparecer.
    outra = await make_org(db)
    await make_member(db, outra, await make_user(db), "org_admin")

    r = await client.get(f"{PREFIX}/organizations", headers=auth(user_id))
    assert r.status_code == 200, r.text
    orgs = r.json()
    assert [o["id"] for o in orgs] == [str(org_id)]
    assert orgs[0]["role"] == "coordinator"


async def test_slug_duplicado_da_409(client, db):
    user_id = await make_user(db)
    slug = rand_slug()
    body = {"slug": slug, "name": "Um"}
    assert (
        await client.post(f"{PREFIX}/organizations", json=body, headers=auth(user_id))
    ).status_code == 201
    r = await client.post(f"{PREFIX}/organizations", json=body, headers=auth(user_id))
    assert r.status_code == 409


# ── Login Google ────────────────────────────────────────────────────────────


async def test_login_sem_convite_da_403(client, db, monkeypatch):
    # Garante que o sistema já tem ao menos uma organização: sem isso, num
    # Postgres genuinamente vazio (CI, primeiro run), count_organizations()
    # == 0 e o login cai no bootstrap (cria org, devolve 200) em vez do 403
    # esperado aqui — o teste passava por acidente localmente só porque o
    # banco de dev tinha organizações reais de sessões anteriores.
    await make_org(db)
    fake_google(monkeypatch, rand_email())
    r = await client.post(f"{PREFIX}/auth/google", json={"access_token": "x"})
    assert r.status_code == 403
    assert "NotInvited" in r.json()["detail"]


async def test_login_dominio_nao_permitido_da_403(client, db, monkeypatch):
    fake_google(monkeypatch, "invasor@gmail.com")
    r = await client.post(f"{PREFIX}/auth/google", json={"access_token": "x"})
    assert r.status_code == 403
    assert "DomainNotAllowed" in r.json()["detail"]


async def test_login_com_convite_cria_usuario_e_vinculo(client, db, monkeypatch):
    org_id = await make_org(db)
    email = rand_email()
    inv_id = await make_invitation(db, org_id, email, role="bioinformatician")
    fake_google(monkeypatch, email, name="Convidado")

    r = await client.post(f"{PREFIX}/auth/google", json={"access_token": "x"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["access_token"]
    assert data["user"]["email"] == email
    assert data["organizations"] == [
        {
            "id": str(org_id),
            "slug": data["organizations"][0]["slug"],
            "name": "Org Teste",
            "role": "bioinformatician",
        }
    ]

    # O convite foi consumido: um segundo login não pode reaproveitá-lo.
    async with db() as s:
        accepted = await s.scalar(
            text("SELECT accepted_at FROM invitations WHERE id = :i"),
            {"i": str(inv_id)},
        )
    assert accepted is not None

    # O token devolvido funciona de verdade.
    token = data["access_token"]
    r = await client.get(
        f"{PREFIX}/me",
        headers={"Authorization": f"Bearer {token}", "X-Organization": str(org_id)},
    )
    assert r.status_code == 200
    assert r.json()["role"] == "bioinformatician"


async def test_login_de_usuario_existente_nao_exige_convite(client, db, monkeypatch):
    email = rand_email()
    user_id = await make_user(db, email=email)
    org_id = await make_org(db)
    await make_member(db, org_id, user_id, "coordinator")
    fake_google(monkeypatch, email)

    r = await client.post(f"{PREFIX}/auth/google", json={"access_token": "x"})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["id"] == str(user_id)
    assert r.json()["organizations"][0]["role"] == "coordinator"


# ── Membros e convites ──────────────────────────────────────────────────────


async def test_listar_membros_da_organizacao(client, db):
    admin = await make_user(db, name="Admin")
    colega = await make_user(db, name="Colega")
    org_id = await make_org(db)
    await make_member(db, org_id, admin, "org_admin")
    await make_member(db, org_id, colega, "lab_tech")

    r = await client.get(f"{PREFIX}/members", headers=auth(admin, org_id=org_id))
    assert r.status_code == 200, r.text
    membros = r.json()
    assert {m["user_id"] for m in membros} == {str(admin), str(colega)}
    assert {m["role"] for m in membros} == {"org_admin", "lab_tech"}


async def test_criar_e_listar_convites(client, db):
    admin = await make_user(db)
    org_id = await make_org(db)
    await make_member(db, org_id, admin, "org_admin")
    convidado = rand_email()

    r = await client.post(
        f"{PREFIX}/invitations",
        json={"email": convidado, "role": "field_tech"},
        headers=auth(admin, org_id=org_id),
    )
    assert r.status_code == 201, r.text
    assert r.json()["email"] == convidado
    assert r.json()["accepted_at"] is None

    r = await client.get(f"{PREFIX}/invitations", headers=auth(admin, org_id=org_id))
    assert r.status_code == 200
    assert [i["email"] for i in r.json()] == [convidado]


async def test_convidar_exige_permissao_member_write(client, db):
    """`viewer` lê, mas não convida. O papel vem do banco, não do JWT."""
    viewer = await make_user(db)
    org_id = await make_org(db)
    await make_member(db, org_id, viewer, "viewer")

    # Mesmo forjando role=org_admin no token, o papel real (viewer) prevalece.
    r = await client.post(
        f"{PREFIX}/invitations",
        json={"email": rand_email(), "role": "lab_tech"},
        headers=auth(viewer, role="org_admin", org_id=org_id),
    )
    assert r.status_code == 403
    assert "member:write" in r.json()["detail"]


async def test_convite_com_papel_invalido_da_422(client, db):
    admin = await make_user(db)
    org_id = await make_org(db)
    await make_member(db, org_id, admin, "org_admin")

    r = await client.post(
        f"{PREFIX}/invitations",
        json={"email": rand_email(), "role": "presidente"},
        headers=auth(admin, org_id=org_id),
    )
    assert r.status_code == 422


# ── Revogar convite, trocar papel, remover membro (rizoma-backend#11) ───────


async def test_revogar_convite(client, db):
    admin = await make_user(db)
    org_id = await make_org(db)
    await make_member(db, org_id, admin, "org_admin")
    inv_id = await make_invitation(db, org_id, rand_email())

    r = await client.delete(f"{PREFIX}/invitations/{inv_id}", headers=auth(admin, org_id=org_id))
    assert r.status_code == 204

    r = await client.get(f"{PREFIX}/invitations", headers=auth(admin, org_id=org_id))
    assert r.json() == []


async def test_revogar_convite_ja_aceito_da_404(client, db):
    """Convite aceito virou filiação — não é mais revogável por aqui."""
    admin = await make_user(db)
    org_id = await make_org(db)
    await make_member(db, org_id, admin, "org_admin")
    email = rand_email()
    inv_id = await make_invitation(db, org_id, email)
    async with db() as s, s.begin():
        await s.execute(
            text("UPDATE invitations SET accepted_at = now() WHERE id = :i"),
            {"i": str(inv_id)},
        )

    r = await client.delete(f"{PREFIX}/invitations/{inv_id}", headers=auth(admin, org_id=org_id))
    assert r.status_code == 404


async def test_revogar_convite_de_outra_organizacao_da_404(client, db):
    """RLS é a rede de segurança, mas o WHERE explícito no repository já
    barra isso antes mesmo de a policy entrar em jogo."""
    admin_a = await make_user(db)
    org_a = await make_org(db, name="Org A")
    await make_member(db, org_a, admin_a, "org_admin")
    org_b = await make_org(db, name="Org B")
    inv_de_b = await make_invitation(db, org_b, rand_email())

    r = await client.delete(f"{PREFIX}/invitations/{inv_de_b}", headers=auth(admin_a, org_id=org_a))
    assert r.status_code == 404


async def test_trocar_papel_de_membro(client, db):
    admin = await make_user(db)
    colega = await make_user(db)
    org_id = await make_org(db)
    await make_member(db, org_id, admin, "org_admin")
    await make_member(db, org_id, colega, "viewer")

    r = await client.patch(
        f"{PREFIX}/members/{colega}/role",
        json={"role": "lab_tech"},
        headers=auth(admin, org_id=org_id),
    )
    assert r.status_code == 204

    r = await client.get(f"{PREFIX}/members", headers=auth(admin, org_id=org_id))
    roles = {m["user_id"]: m["role"] for m in r.json()}
    assert roles[str(colega)] == "lab_tech"


async def test_nao_pode_trocar_o_proprio_papel(client, db):
    admin = await make_user(db)
    org_id = await make_org(db)
    await make_member(db, org_id, admin, "org_admin")

    r = await client.patch(
        f"{PREFIX}/members/{admin}/role",
        json={"role": "viewer"},
        headers=auth(admin, org_id=org_id),
    )
    assert r.status_code == 400


async def test_remover_membro(client, db):
    admin = await make_user(db)
    colega = await make_user(db)
    org_id = await make_org(db)
    await make_member(db, org_id, admin, "org_admin")
    await make_member(db, org_id, colega, "viewer")

    r = await client.delete(f"{PREFIX}/members/{colega}", headers=auth(admin, org_id=org_id))
    assert r.status_code == 204

    r = await client.get(f"{PREFIX}/members", headers=auth(admin, org_id=org_id))
    assert str(colega) not in {m["user_id"] for m in r.json()}


async def test_nao_pode_se_autorremover(client, db):
    admin = await make_user(db)
    org_id = await make_org(db)
    await make_member(db, org_id, admin, "org_admin")

    r = await client.delete(f"{PREFIX}/members/{admin}", headers=auth(admin, org_id=org_id))
    assert r.status_code == 400


async def test_gerenciar_membro_exige_permissao_member_write(client, db):
    viewer = await make_user(db)
    colega = await make_user(db)
    org_id = await make_org(db)
    await make_member(db, org_id, viewer, "viewer")
    await make_member(db, org_id, colega, "viewer")

    r = await client.delete(f"{PREFIX}/members/{colega}", headers=auth(viewer, org_id=org_id))
    assert r.status_code == 403


# ── Isolamento entre organizações (o teste que importa) ─────────────────────


async def test_isolamento_entre_organizacoes(client, db):
    """Usuário da Org A, com JWT válido, apontando para a Org B: 403 em tudo."""
    user_a = await make_user(db)
    org_a = await make_org(db, name="Org A")
    await make_member(db, org_a, user_a, "org_admin")

    user_b = await make_user(db)
    org_b = await make_org(db, name="Org B")
    await make_member(db, org_b, user_b, "org_admin")

    # Na própria org: 200.
    r = await client.get(f"{PREFIX}/members", headers=auth(user_a, org_id=org_a))
    assert r.status_code == 200
    assert [m["user_id"] for m in r.json()] == [str(user_a)]

    # Na org alheia, com header forjado: 403 — não é membro.
    for path in ("/members", "/invitations", "/me"):
        r = await client.get(f"{PREFIX}{path}", headers=auth(user_a, org_id=org_b))
        assert r.status_code == 403, f"{path} vazou: {r.status_code} {r.text}"

    # E /organizations só devolve a própria.
    r = await client.get(f"{PREFIX}/organizations", headers=auth(user_a))
    assert [o["id"] for o in r.json()] == [str(org_a)]


async def test_token_invalido_da_401(client, db):
    r = await client.get(
        f"{PREFIX}/me", headers={"Authorization": "Bearer lixo.nao.jwt"}
    )
    assert r.status_code == 401
