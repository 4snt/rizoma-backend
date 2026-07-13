"""Semeia dados de demonstração do MVP.

Cria duas organizações de propósito. A segunda não é enfeite: é o que permite
provar, com dados reais na tela, que o isolamento entre organizações funciona.

    .venv/bin/python -m scripts.seed_mvp
"""
import asyncio
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.core.security import create_access_token
from app.shared.ids import new_id


def owner_dsn() -> str:
    return (
        f"postgresql+asyncpg://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
    )


async def main() -> None:
    engine = create_async_engine(owner_dsn())

    org_a, org_b = new_id(), new_id()
    user_ana, user_bruno, user_org_b = new_id(), new_id(), new_id()
    cust = new_id()
    proj = new_id()
    samples = [new_id() for _ in range(3)]

    async with engine.begin() as c:
        exists = await c.scalar(text("SELECT count(*) FROM organizations"))
        if exists:
            print("Banco já tem organizações. Rode `make reset` antes de semear.")
            await engine.dispose()
            sys.exit(1)

        await c.execute(
            text(
                "INSERT INTO organizations (id, slug, name) VALUES "
                "(:a,'ufvjm-biotec','UFVJM Biotecnologia Ambiental'),"
                "(:b,'outra-empresa','Outra Empresa (controle de isolamento)')"
            ),
            {"a": str(org_a), "b": str(org_b)},
        )

        await c.execute(
            text(
                "INSERT INTO users (id, email, name) VALUES "
                "(:a,'ana@ufvjm.edu.br','Ana (coordenadora)'),"
                "(:b,'bruno@ufvjm.edu.br','Bruno (responsável técnico)'),"
                "(:c,'carla@ufvjm.edu.br','Carla (outra org)')"
            ),
            {"a": str(user_ana), "b": str(user_bruno), "c": str(user_org_b)},
        )

        # Ana produz o resultado, Bruno revisa. São pessoas diferentes de
        # propósito: o banco RECUSA que o autor aprove o próprio resultado
        # (chk_segregation).
        for uid, org, role in [
            (user_ana, org_a, "org_admin"),
            (user_bruno, org_a, "tech_responsible"),
            (user_org_b, org_b, "org_admin"),
        ]:
            await c.execute(
                text(
                    "INSERT INTO organization_members (id, organization_id, user_id, role) "
                    "VALUES (:i,:o,:u,:r)"
                ),
                {"i": str(new_id()), "o": str(org), "u": str(uid), "r": role},
            )

        await c.execute(
            text(
                "INSERT INTO customers (id, organization_id, name, contact_email, created_by) "
                "VALUES (:i,:o,'Mineradora Vale do Jequitinhonha','contato@exemplo.com',:u)"
            ),
            {"i": str(cust), "o": str(org_a), "u": str(user_ana)},
        )

        await c.execute(
            text(
                "INSERT INTO projects (id, organization_id, customer_id, code, name, "
                "description, marker_type, status, created_by) VALUES "
                "(:i,:o,:c,'INOVAHERB','INOVAHERB — micobioma de solo',"
                "'Efeito de herbicidas sobre a comunidade fúngica do solo.','ITS','in_progress',:u)"
            ),
            {"i": str(proj), "o": str(org_a), "c": str(cust), "u": str(user_ana)},
        )

        for n, sid in enumerate(samples, start=1):
            await c.execute(
                text(
                    "INSERT INTO samples (id, organization_id, project_id, code, matrix, "
                    "treatment_group, replicate, status, geom, collected_by, occurred_at) VALUES "
                    "(:i,:o,:p,:code,'solo',:grp,:rep,'planned',"
                    " ST_SetSRID(ST_MakePoint(:lon,:lat),4326)::geography,:u, now() - interval '2 days')"
                ),
                {
                    "i": str(sid), "o": str(org_a), "p": str(proj),
                    "code": f"AM-{n:03d}", "grp": "controle" if n == 1 else "tratado",
                    "rep": n, "u": str(user_ana),
                    "lon": -43.6 - n * 0.01, "lat": -18.2 - n * 0.01,
                },
            )

        # Projeto da Org B — existe só para o teste de isolamento ter o que NÃO ver.
        await c.execute(
            text(
                "INSERT INTO projects (id, organization_id, code, name, status, created_by) "
                "VALUES (:i,:o,'SEGREDO-B','Projeto confidencial da Org B','in_progress',:u)"
            ),
            {"i": str(new_id()), "o": str(org_b), "u": str(user_org_b)},
        )

    await engine.dispose()

    print("\n✅ Seed concluído.\n")
    print(f"Org A (UFVJM):  {org_a}")
    print(f"Org B (outra):  {org_b}\n")
    print("Tokens de teste (Bearer):\n")
    print(f"  Ana (org_admin, Org A)\n    {create_access_token(str(user_ana), 'org_admin')}\n")
    print(f"  Bruno (tech_responsible, Org A)\n    {create_access_token(str(user_bruno), 'tech_responsible')}\n")
    print(f"  Carla (org_admin, Org B)\n    {create_access_token(str(user_org_b), 'org_admin')}\n")
    print("Teste de isolamento — com o token da Carla, tente ler o projeto da Org A:")
    print(f"  curl -H 'Authorization: Bearer <carla>' -H 'X-Organization: {org_a}' \\")
    print("       http://localhost:8000/api/v2/lims/projects")
    print("  → deve responder 403. Se listar o INOVAHERB, o isolamento quebrou.\n")


if __name__ == "__main__":
    asyncio.run(main())
