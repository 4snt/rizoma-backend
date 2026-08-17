# ADR-012 — Provedor OAuth por trás de um adapter (inversão de dependência)

Status: aceita
Data: 2026-08-17

## Contexto

`login_with_google` chamava `verify_google_token` diretamente — uma
função solta em `app/core/google_auth.py`, acoplada ao formato de claims
específico do endpoint `userinfo` do Google. ADR-005 já decidiu OAuth-only
(sem senha), mas amarrado a UM provedor específico no código: trocar ou
somar um segundo provedor (Microsoft, GitHub, um IdP próprio de outra
instituição que rode o Rizoma) exigiria reescrever `login_with_google`
inteira, não só plugar algo novo.

O Rizoma é software livre (GPL-3.0). Um laboratório que rode sua própria
instância pode não usar Google Workspace — a decisão institucional de
"só Google" (ADR-005) é do NEBIM, não uma limitação da plataforma.

## Decisão

`app/modules/identity/oauth.py` define o contrato: `OAuthClaims`
(formato normalizado — sub, email, name, avatar_url, email_verified) e
`OAuthProvider` (Protocol com um único método, `verify(access_token) ->
OAuthClaims`). `GoogleOAuthProvider` é o adapter de hoje, implementando
esse contrato por cima do endpoint `userinfo` do Google.

A injeção acontece na borda HTTP: a rota `POST /auth/google` recebe
`provider: OAuthProvider = Depends(get_oauth_provider)` e repassa pra
`service.login_with_google(body, provider)`. O serviço nunca instancia
`GoogleOAuthProvider()` ele mesmo — só conhece a interface. Trocar de
provedor (ou testar com um fake) é trocar o que `get_oauth_provider()`
devolve, sem tocar na lógica de login/convite/bootstrap.

Fica de fora desta ADR (não implementado): uma segunda rota
(`/auth/microsoft` ou genérica `/auth/{provider}`), e generalizar a
coluna `users.google_sub` (hoje nomeada especificamente pro Google) pra
algo como `oauth_sub` + `oauth_provider`. Ambos são trabalho real de
"adicionar o segundo provedor", propositalmente não antecipado sem um
caso de uso concreto — a ADR só garante que o ponto de extensão existe.

## Alternativas

- **Manter função solta, parametrizar por string (`provider: str`).**
  Descartada: viraria um `if/elif` crescente dentro do serviço, exatamente
  o acoplamento que se queria evitar.
- **Strategy via herança (classe base abstrata) em vez de `Protocol`.**
  Descartada por preferência: `Protocol` (PEP 544) dá o mesmo contrato
  sem forçar `GoogleOAuthProvider` a herdar de nada — importa só pra quem
  faz type-check, não em runtime.

## Consequências

Fica mais fácil: adicionar um provedor novo é escrever uma classe que
implementa `verify()` e trocar `get_oauth_provider()` — zero mudança em
`login_with_google`, `router.py` ganha só uma rota nova quando existir.
Testar fica mais direto: `fake_google()` monkeypatcha
`GoogleOAuthProvider.verify` (ou, com dependency override do FastAPI,
substitui `get_oauth_provider` inteiro).

Fica mais difícil: uma camada de indireção a mais pra ler quando alguém
não conhece o padrão — `service.py` já não mostra na cara que é
"Google" especificamente, só "um provedor OAuth qualquer".
