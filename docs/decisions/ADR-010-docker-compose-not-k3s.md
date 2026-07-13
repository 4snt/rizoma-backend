# ADR-010 — Docker Compose até doer; k3s adiado

Status: aceita
Data: 2026-07-13

## Contexto

O repositório já tem `infra/manifests/` com deployments k3s, distribuídos por nó:
o R Worker num agente com taint dedicado, a API noutro, Postgres e MinIO num
terceiro. É uma topologia bonita — para um time com pessoa de plantão.

Quem opera isso é **uma pessoa**, que também é quem escreve o backend, o
frontend, a análise estatística e o TCC.

O k3s cobra antes de entregar: rede overlay que falha de um jeito só dela,
PersistentVolume e StorageClass, Ingress e cert-manager, RBAC, `kubectl describe`
como ferramenta de depuração cotidiana, e um upgrade de cluster que é um evento.
Nenhum desses custos compra nada que o MVP precise — não há tráfego que exija
escala horizontal, nem SLA que exija auto-healing entre nós.

O que o projeto realmente precisa é: subir, não perder dado, e ter backup que
alguém já testou restaurar.

## Decisão

**Docker Compose numa VM.** Postgres, MinIO, API e (sob perfil separado) o R
Worker. Cloudflare na frente. Backup offsite do volume do Postgres e do bucket,
com restore testado — testado de verdade, não "o script existe".

Os manifests k3s ficam onde estão, como referência, mas não são o caminho de
implantação do MVP.

**Gatilho de reversão, explícito.** Migrar para k3s (ou equivalente) quando
acontecer pelo menos um destes, e não antes:

- for preciso rodar mais de uma réplica da API por causa de carga real;
- o R Worker precisar de máquinas separadas e elásticas para dar conta da fila;
- a indisponibilidade durante um deploy passar a ser inaceitável para um usuário
  que existe;
- houver mais de uma pessoa de plantão.

Enquanto nenhum deles for verdade, o Compose está certo.

## Alternativas

- **k3s agora (o que estava no repo).** Descartada: custo operacional alto,
  benefício zero no volume atual.
- **PaaS (Coolify, Railway, Fly).** Parcialmente mantida — existe um
  `docker-compose.coolify.yml`, e o Coolify é essencialmente Compose gerenciado.
  É uma evolução aceitável, não uma mudança de rumo.
- **Kubernetes gerenciado (EKS/GKE).** Descartada: mesma complexidade do k3s, com
  fatura.

## Consequências

Fica mais fácil: `docker compose up -d` e está no ar; depurar é `docker logs`;
o mesmo arquivo descreve dev e produção, então "funciona na minha máquina" para
de ser uma frase; sobra tempo para o que é o projeto.

Fica mais difícil: deploy tem janela de indisponibilidade (aceitável hoje); não
há auto-healing entre máquinas — se a VM morre, alguém precisa agir; escalar é
vertical (VM maior) até o gatilho acima disparar; e a migração futura para k3s
será um trabalho concentrado, em vez de diluído — o que é uma troca consciente,
porque boa parte dos projetos nunca chega lá.
