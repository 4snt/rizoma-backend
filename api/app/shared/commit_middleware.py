"""Commita a transação da requisição ANTES de a resposta sair.

Por que existe: `get_ctx` abre a transação e commitava no teardown do
`yield`. A partir do FastAPI 0.118 esse teardown roda DEPOIS de a resposta
já ter sido enviada ao cliente. Consequências reais:
  - o cliente recebe 201 e a próxima requisição dele pode não enxergar o
    que acabou de criar (read-after-write furado — visto no import do
    histórico NEBIM: `POST /samples` 201 seguido de `POST .../tests` 404);
  - se o commit falhar, o cliente já foi embora com um 2xx falso.

Este middleware ASGI puro intercepta o `http.response.start` e commita a
sessão que `get_ctx` deixou em `scope["state"]` — mas só em status < 400.
Em 4xx/5xx não commita: o teardown de `get_ctx` faz rollback, como antes.
Se o commit falhar aqui, a exceção sobe antes de qualquer byte sair.

O teardown de `get_ctx` continua commitando se ainda houver transação
aberta — é o fallback para apps montados sem este middleware (os testes
sobem um `FastAPI()` só com o router).
"""
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.types import ASGIApp, Message, Receive, Scope, Send

SESSION_STATE_KEY = "db_session"


class CommitBeforeResponseMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start" and message.get("status", 500) < 400:
                # `request.state.x = ...` grava em scope["state"] (dict).
                session: AsyncSession | None = scope.get("state", {}).get(SESSION_STATE_KEY)
                if session is not None and session.in_transaction():
                    await session.commit()
            await send(message)

        await self.app(scope, receive, send_wrapper)
