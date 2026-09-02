# ADR-014 — Reversão pontual da ADR-010: k3s/MicroK8s para comparação ao vivo com SENAITE

Status: aceita
Data: 2026-09-02

## Contexto

A [ADR-010](ADR-010-docker-compose-not-k3s.md) decidiu adiar Kubernetes e operar
em Docker Compose numa VM única, com gatilhos de reversão explícitos: mais de
uma réplica da API por carga real, o R Worker precisando de máquinas elásticas
separadas, indisponibilidade de deploy inaceitável para um usuário real, ou
mais de uma pessoa de plantão. **Nenhum desses gatilhos se tornou verdadeiro.**
O ambiente continua operado por uma pessoa só, sem carga de produção real.

O motivo desta reversão é outro: o capítulo `AnalisePadroesLIMS.tex` do TCC
compara o Rizoma a soluções de mercado (SENAITE, OpenELIS, Baobab LIMS,
QIIME2, Galaxy etc.) só na literatura — tabelas de funcionalidades e padrões
arquiteturais. Para a defesa, o autor decidiu que a comparação ganha peso
sendo demonstrada ao vivo: o Rizoma e o SENAITE (o LIMS open source genérico
mais próximo, sucessor do Bika LIMS, topo da tabela comparativa) rodando lado
a lado, publicamente acessíveis, no mesmo domínio.

Isso não é um requisito operacional do produto — é um requisito da
demonstração acadêmica. A ADR-010 continua correta para o motivo que a
fundamentou; esta ADR não a invalida, só abre uma exceção explícita e
datada para esse propósito.

## Decisão

Um cluster Kubernetes de nó único (MicroK8s, já presente no servidor,
reaproveitado em vez de instalar k3s do zero) hospeda o Rizoma
(frontend + API + R Worker + Postgres + MinIO) e o SENAITE, lado a lado, no
namespace `bioinformatica`. O Docker Compose existente (Traefik, Portainer,
Vaultwarden, Uptime Kuma) continua no ar, intocado — o cluster k8s coexiste
com ele; o Traefik do Compose só ganhou uma rota nova encaminhando os hosts
`rizoma.flipafile.com`, `senaite.flipafile.com` e `s3-rizoma.flipafile.com`
para o ingress do cluster.

Os manifests de referência que já existiam em `infra/manifests/` (nunca usados
como caminho de implantação, per ADR-010) foram a base do módulo Terraform em
`infra/terraform-local/`, adaptados para nó único (sem os `nodeSelector`
`agent-1/2/4` originais, que assumiam um cluster que nunca existiu de fato) e
para MicroK8s (ingress Traefik interno ao cluster, `ingressClassName: public`,
em vez do `ingress-nginx` do manifest original).

## Gatilho de reversão desta reversão

Depois da defesa do TCC, se nenhuma nova necessidade operacional surgir, o
cluster k8s local deve ser desligado e o SENAITE removido — ele existe só
para a comparação, não é parte do produto. A ADR-010 volta a valer sem
ressalvas nesse momento.

## Consequências

Ganha: comparação lado a lado real, navegável, para a banca — não só uma
tabela no texto.

Perde: exatamente o custo operacional que a ADR-010 já apontava (rede
overlay, PVC/StorageClass, um segundo sistema de deploy a manter em paralelo
ao Compose) — assumido conscientemente, por tempo limitado, só pelo motivo
acima.
