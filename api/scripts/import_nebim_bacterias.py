"""Importa o histórico de bactérias isoladas (Testes_Bacterias.csv) como
amostras reais do LIMS.

Standalone, roda uma vez, fala com a API real via HTTP — não vai direto no
banco, pra respeitar RLS/validação/idempotência já implementadas em vez de
duplicar regra de negócio num script solto.

O projeto de destino precisa existir antes (crie via UI ou
`POST /api/v2/lims/projects`, ex. código "NEBIM-ISOLADOS") — o script não
cria projeto, pra não decidir por você quem é o dono/organização.

Uso:
    .venv/bin/python -m scripts.import_nebim_bacterias \\
        --project-id <uuid> \\
        --token <jwt> \\
        --csv-path "/home/guilherme-carneiro/repo/Projeto de mestrado/Testes_Bacterias.csv" \\
        --base-url http://localhost:8000
"""
import argparse
import csv
import hashlib
import sys

import httpx

# Colunas de enzima do CSV -> viram uma linha em sample_tests cada, com o
# valor bruto tal como está (+, -, ++, -+, N, ou texto anômalo) — sem
# normalizar aqui; normalização é assunto de relatório, não de importação.
ENZIME_COLUMNS = [
    "Catalase", "Esterase", "Urease", "Hipersensibilidade",
    "Fosfatase Acida", "Fosfatase Alcalina", "Oxidase", "Sideroforos",
    "Producao AIA", "Desoxigenase", "Desalogenase",
]


def idempotency_key(code: str) -> str:
    return f"nebim-import-{hashlib.sha256(code.encode()).hexdigest()[:16]}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project-id", required=True, help="UUID do projeto já criado")
    ap.add_argument("--token", required=True, help="JWT de um usuário com sample:write")
    ap.add_argument(
        "--csv-path",
        default="/home/guilherme-carneiro/repo/Projeto de mestrado/Testes_Bacterias.csv",
    )
    ap.add_argument("--base-url", default="http://localhost:8000")
    args = ap.parse_args()

    headers = {"Authorization": f"Bearer {args.token}"}
    created_samples, replayed_samples, created_tests, warnings = 0, 0, 0, []

    with httpx.Client(base_url=args.base_url, headers=headers, timeout=30) as client:
        with open(args.csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                code = (row.get("Etiqueta") or "").strip()
                if not code:
                    continue
                bac = (row.get("Bac") or "").strip() or None

                body = {
                    "code": code,
                    "matrix": "cultura_microbiana",
                    "organism_type": "bacteria",
                    "treatment_group": bac,
                }
                r = client.post(
                    f"/api/v2/lims/projects/{args.project_id}/samples",
                    json=body,
                    headers={"Idempotency-Key": idempotency_key(code)},
                )
                if r.status_code not in (200, 201):
                    warnings.append(f"{code}: falha ao criar amostra ({r.status_code} {r.text})")
                    continue
                sample_id = r.json()["id"]
                if r.headers.get("Idempotent-Replay") == "true":
                    replayed_samples += 1
                else:
                    created_samples += 1

                # Idempotência dos testes: a Idempotency-Key só cobre a amostra.
                # UNIQUE(sample_id, test_name, tested_at) não segura reimport
                # porque tested_at é NULL aqui (NULL != NULL) — então pula o
                # que já existe por nome.
                existing = client.get(f"/api/v2/lims/samples/{sample_id}/tests")
                if existing.status_code != 200:
                    warnings.append(
                        f"{code}: falha ao listar testes existentes "
                        f"({existing.status_code} {existing.text}); testes pulados"
                    )
                    continue
                already = {t["test_name"] for t in existing.json()}

                for column in ENZIME_COLUMNS:
                    value = (row.get(column) or "").strip()
                    if not value or column in already:
                        continue
                    tr = client.post(
                        f"/api/v2/lims/samples/{sample_id}/tests",
                        json={"test_name": column, "result": value},
                    )
                    if tr.status_code != 201:
                        warnings.append(
                            f"{code}/{column}: falha ao criar teste "
                            f"({tr.status_code} {tr.text})"
                        )
                        continue
                    created_tests += 1

    print(
        f"{created_samples} amostra(s) criada(s), {replayed_samples} já existente(s), "
        f"{created_tests} teste(s) criado(s)."
    )
    if warnings:
        print(f"{len(warnings)} aviso(s):", file=sys.stderr)
        for w in warnings:
            print(f"  - {w}", file=sys.stderr)


if __name__ == "__main__":
    main()
