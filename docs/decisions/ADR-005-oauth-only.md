# ADR-005 — Só OAuth, sem senha

Status: aceita
Data: 2026-07-13

## Contexto

A v1 previa "MFA, senha, recuperação de senha, Google, Microsoft" — ou seja, um
sistema de autenticação próprio **e** federado, os dois.

Autenticação por senha não é uma tela de login. É: política de senha, hashing e
sua rotação, throttle de tentativas, bloqueio de conta, fluxo de recuperação por
email (com token de uso único e expiração), fluxo de troca, MFA (TOTP, códigos de
recuperação, dispositivos confiáveis) e a superfície de ataque de tudo isso. É um
subsistema inteiro, e é o subsistema onde um erro vira vazamento.

O público do Rizoma é institucional: todo usuário tem conta `@ufvjm.edu.br`, que
já é Google Workspace, que já tem MFA imposto pela instituição.

## Decisão

Autenticação **exclusivamente** por OAuth/OIDC — Google no MVP, Microsoft depois
se aparecer instituição que use. Nenhuma senha é armazenada, em nenhuma forma. O
backend valida o token do provedor e emite um JWT próprio (HS256) com o papel do
usuário.

Acesso restrito ao domínio `@ufvjm.edu.br`, e usuário novo precisa de convite
(`403 NotInvited`).

Consequência direta no código: `passlib` e `bcrypt` saem do `requirements.txt`.
Não há hash de senha porque não há senha.

## Alternativas

- **Senha + OAuth (o "os dois" da v1).** Descartada: paga todo o custo do
  subsistema de senha para atender zero usuário que não tem conta Google.
- **Magic link por email.** Descartada: elimina a senha, mas transforma a caixa
  de email num fator único e obriga a operar entrega de email transacional. O
  IdP já faz isso melhor.
- **IdP próprio (Keycloak).** Descartada: um serviço stateful a mais, para um
  problema que o Google já resolve.

## Consequências

Fica mais fácil: sumiram política de senha, reset, troca, throttle e MFA próprio;
o MFA passa a ser responsabilidade do IdP, que o faz melhor; a base de dados não
tem nada que valha roubar em termos de credencial.

Fica mais difícil: dependência dura do Google — se o OAuth cair, ninguém entra, e
não há caminho alternativo; usuário sem conta no domínio não tem como acessar
(o que é o comportamento desejado, mas fecha a porta para colaborador externo sem
antes criar uma conta institucional); testes de integração precisam mockar o IdP.
