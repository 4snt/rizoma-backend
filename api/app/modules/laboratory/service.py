"""Regras de domínio dos resultados de laboratório.

O banco já recusa UPDATE/DELETE em `result_versions` (trigger append-only) e já
tem CHECKs para justificativa-na-correção e segregação de funções. Este módulo
NÃO tenta contornar nada disso — ele antecipa as violações para devolver um erro
HTTP com significado, em vez de deixar vazar um 500 do Postgres.

Corrigir um resultado = INSERT de uma versão nova apontando para a anterior.
A versão antiga continua no banco, intacta. É essa a prova que um auditor pede.
"""
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.context import Ctx
from app.shared.ids import new_id

_VERSION_COLS = """
    id, result_id, version, value_numeric, value_text, unit, lod, loq,
    uncertainty, below_lod, status, supersedes, change_reason,
    created_by, reviewed_by, created_at
"""


def display_value(
    value_numeric: Decimal | None,
    value_text: str | None,
    lod: Decimal | None,
    below_lod: bool,
) -> str:
    """Como o resultado deve ser LIDO por um humano.

    Abaixo do limite de detecção, o resultado não é "0" e não é "desconhecido":
    é "<LOD". Imprimir 0 afirma ausência que o método não mediu; imprimir null
    esconde uma medição que aconteceu. Ambos falsificam o laudo.
    """
    if below_lod and lod is not None:
        return f"<{lod}"
    if value_numeric is not None:
        return str(value_numeric)
    return value_text or ""


def _is_below_lod(value_numeric: Decimal | None, lod: Decimal | None) -> bool:
    return value_numeric is not None and lod is not None and value_numeric < lod


def _version_out(row) -> dict:
    d = dict(row._mapping)
    d["display_value"] = display_value(
        d["value_numeric"], d["value_text"], d["lod"], d["below_lod"]
    )
    return d


async def _load_current_version(session: AsyncSession, result_id: UUID):
    """A versão corrente é a de maior `version` — nunca a "última editada",
    porque editar não existe aqui."""
    return (
        await session.execute(
            text(
                f"SELECT {_VERSION_COLS} FROM result_versions "
                "WHERE result_id = :r ORDER BY version DESC LIMIT 1"
            ),
            {"r": str(result_id)},
        )
    ).first()


async def _require_result(session: AsyncSession, result_id: UUID):
    row = (
        await session.execute(
            text("SELECT id, sample_id, analyte, method, created_at FROM lab_results WHERE id = :i"),
            {"i": str(result_id)},
        )
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resultado não encontrado.")
    return row


async def create_result(ctx: Ctx, sample_id: UUID, data) -> dict:
    ctx.require("result:write")
    s = ctx.session

    exists = (
        await s.execute(text("SELECT 1 FROM samples WHERE id = :i"), {"i": str(sample_id)})
    ).first()
    if exists is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Amostra não encontrada.")

    if data.value_numeric is None and not data.value_text:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Informe value_numeric ou value_text — um resultado sem valor não é um resultado.",
        )

    result_id = new_id()
    await s.execute(
        text(
            "INSERT INTO lab_results (id, organization_id, sample_id, analyte, method) "
            "VALUES (:i, :o, :s, :a, :m)"
        ),
        {
            "i": str(result_id),
            "o": str(ctx.org_id),
            "s": str(sample_id),
            "a": data.analyte,
            "m": data.method,
        },
    )

    below = _is_below_lod(data.value_numeric, data.lod)
    await s.execute(
        text(
            f"""
            INSERT INTO result_versions (
                id, organization_id, result_id, version, value_numeric, value_text,
                unit, lod, loq, uncertainty, below_lod, status, created_by
            ) VALUES (
                :i, :o, :r, 1, :vn, :vt, :u, :lod, :loq, :unc, :below, 'submitted', :cb
            )
            """
        ),
        {
            "i": str(new_id()),
            "o": str(ctx.org_id),
            "r": str(result_id),
            "vn": data.value_numeric,
            "vt": data.value_text,
            "u": data.unit,
            "lod": data.lod,
            "loq": data.loq,
            "unc": data.uncertainty,
            "below": below,
            "cb": str(ctx.user_id),
        },
    )
    return await get_result(ctx, result_id, permission="result:write")


async def get_result(ctx: Ctx, result_id: UUID, permission: str = "result:read") -> dict:
    ctx.require(permission)
    s = ctx.session
    head = await _require_result(s, result_id)

    rows = (
        await s.execute(
            text(
                f"SELECT {_VERSION_COLS} FROM result_versions "
                "WHERE result_id = :r ORDER BY version"
            ),
            {"r": str(result_id)},
        )
    ).fetchall()
    history = [_version_out(r) for r in rows]
    return {
        "id": head.id,
        "sample_id": head.sample_id,
        "analyte": head.analyte,
        "method": head.method,
        "created_at": head.created_at,
        "current": history[-1],
        "history": history,
    }


async def list_results(ctx: Ctx, sample_id: UUID) -> list[dict]:
    """Cada resultado vem com a versão corrente E o histórico completo.

    O histórico não é um extra: sem ele, uma correção é indistinguível de uma
    mentira.
    """
    ctx.require("result:read")
    s = ctx.session

    ids = (
        await s.execute(
            text("SELECT id FROM lab_results WHERE sample_id = :s ORDER BY created_at"),
            {"s": str(sample_id)},
        )
    ).fetchall()
    return [await get_result(ctx, r.id) for r in ids]


async def correct_result(ctx: Ctx, result_id: UUID, data) -> dict:
    """Versão N+1 apontando para a N. A N continua lá."""
    ctx.require("result:write")
    s = ctx.session
    await _require_result(s, result_id)

    if not data.change_reason or not data.change_reason.strip():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "change_reason é obrigatório para corrigir um resultado: uma correção "
            "sem justificativa não explica nada a um auditor (ISO 17025).",
        )

    prev = await _load_current_version(s, result_id)
    if prev is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resultado sem versões.")

    # Campos não informados herdam a versão anterior — corrigir a unidade não
    # deve apagar o LOD.
    value_numeric = data.value_numeric if data.value_numeric is not None else prev.value_numeric
    value_text = data.value_text if data.value_text is not None else prev.value_text
    unit = data.unit or prev.unit
    lod = data.lod if data.lod is not None else prev.lod
    loq = data.loq if data.loq is not None else prev.loq
    uncertainty = data.uncertainty if data.uncertainty is not None else prev.uncertainty
    below = _is_below_lod(value_numeric, lod)

    await s.execute(
        text(
            """
            INSERT INTO result_versions (
                id, organization_id, result_id, version, value_numeric, value_text,
                unit, lod, loq, uncertainty, below_lod, status, supersedes,
                change_reason, created_by
            ) VALUES (
                :i, :o, :r, :v, :vn, :vt, :u, :lod, :loq, :unc, :below, 'submitted',
                :sup, :reason, :cb
            )
            """
        ),
        {
            "i": str(new_id()),
            "o": str(ctx.org_id),
            "r": str(result_id),
            "v": prev.version + 1,
            "vn": value_numeric,
            "vt": value_text,
            "u": unit,
            "lod": lod,
            "loq": loq,
            "unc": uncertainty,
            "below": below,
            "sup": str(prev.id),
            "reason": data.change_reason,
            "cb": str(ctx.user_id),
        },
    )
    return await get_result(ctx, result_id, permission="result:write")


async def review_result(ctx: Ctx, result_id: UUID, data) -> dict:
    """Aprova (ou retrata) criando a versão N+1.

    Segregação de funções: quem PRODUZIU o resultado não pode aprová-lo. Validado
    aqui para dar 403 com explicação; o CHECK `chk_segregation` no banco é a rede
    de segurança embaixo.

    Detalhe que importa: a nova versão carrega `created_by` do PRODUTOR ORIGINAL,
    não do revisor. É o que mantém a autoria correta na trilha (e o que faz o
    CHECK reviewed_by <> created_by significar o que deve significar).
    """
    ctx.require("result:review")
    s = ctx.session
    await _require_result(s, result_id)

    prev = await _load_current_version(s, result_id)
    if prev is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resultado sem versões.")

    if prev.created_by == ctx.user_id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Segregação de funções: quem produziu o resultado não pode aprová-lo.",
        )

    reason = data.note or (
        "Aprovação técnica." if data.status == "approved" else "Resultado retratado."
    )
    await s.execute(
        text(
            """
            INSERT INTO result_versions (
                id, organization_id, result_id, version, value_numeric, value_text,
                unit, lod, loq, uncertainty, below_lod, status, supersedes,
                change_reason, created_by, reviewed_by
            ) VALUES (
                :i, :o, :r, :v, :vn, :vt, :u, :lod, :loq, :unc, :below, :st,
                :sup, :reason, :cb, :rb
            )
            """
        ),
        {
            "i": str(new_id()),
            "o": str(ctx.org_id),
            "r": str(result_id),
            "v": prev.version + 1,
            "vn": prev.value_numeric,
            "vt": prev.value_text,
            "u": prev.unit,
            "lod": prev.lod,
            "loq": prev.loq,
            "unc": prev.uncertainty,
            "below": prev.below_lod,
            "st": data.status,
            "sup": str(prev.id),
            "reason": reason,
            "cb": str(prev.created_by),
            "rb": str(ctx.user_id),
        },
    )
    return await get_result(ctx, result_id, permission="result:review")
