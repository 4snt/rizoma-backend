# Guia de Implementação — Sistema de Login

> Contexto: plataforma acadêmica de bioinformática (TCC). Dois perfis de acesso:
> **researcher** (leitura + upload de amostras) e **admin** (criação de projetos, gerenciamento de usuários).

---

## 1. Modelo de dados

```sql
-- db/migrations/004_auth.sql
CREATE TABLE users (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email         VARCHAR(255) NOT NULL UNIQUE,
    name          VARCHAR(255) NOT NULL,
    hashed_password TEXT NOT NULL,
    role          VARCHAR(20) NOT NULL DEFAULT 'researcher'
                  CHECK (role IN ('researcher', 'admin')),
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Índice para lookup por email (login)
CREATE INDEX idx_users_email ON users(email);

-- Permissões
GRANT SELECT, INSERT, UPDATE ON users TO api_user;
```

---

## 2. Stack de autenticação

| Camada | Biblioteca | Papel |
|--------|-----------|-------|
| Backend | `python-jose[cryptography]` | Gera/valida JWT |
| Backend | `passlib[bcrypt]` | Hash de senha |
| Frontend | `next-auth` v5 | Sessão + cookies httpOnly |
| Frontend | `next-auth/providers/credentials` | Login com email+senha |

### Instalar

```bash
# backend
pip install "python-jose[cryptography]" "passlib[bcrypt]"

# frontend
npm install next-auth@beta
```

---

## 3. Backend — FastAPI

### 3.1 Configuração JWT (`api/app/core/security.py`)

```python
from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext
from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def create_access_token(sub: str, role: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=settings.jwt_access_minutes)
    return jwt.encode(
        {"sub": sub, "role": role, "exp": expire},
        settings.jwt_secret, algorithm="HS256",
    )

def create_refresh_token(sub: str) -> str:
    expire = datetime.utcnow() + timedelta(days=settings.jwt_refresh_days)
    return jwt.encode(
        {"sub": sub, "type": "refresh", "exp": expire},
        settings.jwt_secret, algorithm="HS256",
    )

def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
```

### 3.2 Variáveis de ambiente (adicionar ao `.env.example`)

```
JWT_SECRET=troque-por-string-aleatoria-longa
JWT_ACCESS_MINUTES=30
JWT_REFRESH_DAYS=7
```

### 3.3 Dependency de autenticação (`api/app/core/auth_deps.py`)

```python
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError
from app.core.security import decode_token

bearer = HTTPBearer(auto_error=False)

async def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(bearer),
) -> dict:
    if not creds:
        raise HTTPException(status_code=401, detail="Não autenticado")
    try:
        payload = decode_token(creds.credentials)
        return {"user_id": payload["sub"], "role": payload["role"]}
    except JWTError:
        raise HTTPException(status_code=401, detail="Token inválido ou expirado")

def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")
    return user
```

### 3.4 Router de autenticação (`api/app/api/v1/auth.py`)

```python
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, EmailStr
from app.core.database import get_pool
from app.core.security import verify_password, create_access_token, create_refresh_token, decode_token

router = APIRouter()

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

@router.post("/login")
async def login(body: LoginRequest, response: Response):
    pool = get_pool()
    async with pool.acquire() as conn:
        user = await conn.fetchrow(
            "SELECT id, hashed_password, role, is_active FROM users WHERE email = $1",
            body.email,
        )
    if not user or not verify_password(body.password, user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Credenciais inválidas")
    if not user["is_active"]:
        raise HTTPException(status_code=403, detail="Conta desativada")

    uid = str(user["id"])
    access  = create_access_token(uid, user["role"])
    refresh = create_refresh_token(uid)

    # Refresh token em cookie httpOnly (não exposto ao JS)
    response.set_cookie("refresh_token", refresh, httponly=True,
                        samesite="lax", max_age=7*86400)
    return {"access_token": access, "token_type": "bearer", "role": user["role"]}

@router.post("/refresh")
async def refresh(request: Request, response: Response):
    token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(status_code=401, detail="Refresh token ausente")
    try:
        payload = decode_token(token)
        if payload.get("type") != "refresh":
            raise ValueError
    except Exception:
        raise HTTPException(status_code=401, detail="Refresh token inválido")

    # Busca role atual do usuário
    pool = get_pool()
    async with pool.acquire() as conn:
        user = await conn.fetchrow("SELECT role FROM users WHERE id = $1", payload["sub"])
    if not user:
        raise HTTPException(status_code=401, detail="Usuário não encontrado")

    new_access = create_access_token(payload["sub"], user["role"])
    return {"access_token": new_access, "token_type": "bearer"}

@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("refresh_token")
    return {"detail": "Sessão encerrada"}
```

### 3.5 Registrar em `main.py`

```python
from app.api.v1 import auth
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
```

### 3.6 Proteger rotas existentes

```python
# Exemplo: só researchers autenticados podem criar amostras
from app.core.auth_deps import get_current_user

@router.post("/presigned-pair")
async def get_presigned_pair(body: ..., user=Depends(get_current_user)):
    ...

# Só admins criam projetos
@router.post("/")
async def create_project(body: ..., user=Depends(require_admin)):
    ...
```

---

## 4. Frontend — Next.js (NextAuth v5)

### 4.1 `auth.ts` (raiz do bio-frontend)

```typescript
import NextAuth from "next-auth"
import Credentials from "next-auth/providers/credentials"

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"

export const { handlers, signIn, signOut, auth } = NextAuth({
  providers: [
    Credentials({
      credentials: {
        email:    { label: "E-mail",  type: "email" },
        password: { label: "Senha",   type: "password" },
      },
      async authorize(credentials) {
        const res = await fetch(`${API}/api/v1/auth/login`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(credentials),
        })
        if (!res.ok) return null
        const data = await res.json()
        return { accessToken: data.access_token, role: data.role }
      },
    }),
  ],
  callbacks: {
    jwt({ token, user }) {
      if (user) {
        token.accessToken = (user as any).accessToken
        token.role        = (user as any).role
      }
      return token
    },
    session({ session, token }) {
      (session as any).accessToken = token.accessToken
      ;(session as any).role       = token.role
      return session
    },
  },
  pages: { signIn: "/login" },
})
```

### 4.2 Route handler (`app/api/auth/[...nextauth]/route.ts`)

```typescript
import { handlers } from "@/auth"
export const { GET, POST } = handlers
```

### 4.3 Middleware de proteção (`middleware.ts` — raiz)

```typescript
import { auth } from "@/auth"
import { NextResponse } from "next/server"

export default auth((req) => {
  const isLoggedIn = !!req.auth
  const isAuthPage = req.nextUrl.pathname.startsWith("/login")

  if (!isLoggedIn && !isAuthPage) {
    return NextResponse.redirect(new URL("/login", req.url))
  }
})

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico).*)"],
}
```

### 4.4 Página de login (`app/login/page.tsx`)

```tsx
"use client"
import { signIn } from "next-auth/react"
import { useState } from "react"
import { useRouter } from "next/navigation"

export default function LoginPage() {
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [error, setError] = useState("")
  const router = useRouter()

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const res = await signIn("credentials", {
      email, password, redirect: false,
    })
    if (res?.error) setError("Credenciais inválidas")
    else router.push("/")
  }

  return (
    <main style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100vh", background: "var(--bg)" }}>
      <div className="card" style={{ padding: 32, width: 360 }}>
        <div style={{ marginBottom: 24, textAlign: "center" }}>
          <span style={{ fontSize: 32 }}>🧬</span>
          <h1 className="glow-cyan" style={{ fontSize: 20, fontWeight: 700, marginTop: 8 }}>Bio-Platform</h1>
          <p style={{ color: "var(--text-2)", fontSize: 13, marginTop: 4 }}>TCC · Bioinformática</p>
        </div>
        <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div>
            <label style={{ fontSize: 12, color: "var(--text-2)", display: "block", marginBottom: 6 }}>E-mail</label>
            <input type="email" value={email} onChange={e => setEmail(e.target.value)} required
              style={{ width: "100%", background: "var(--surface-2)", border: "1px solid var(--border)",
                borderRadius: 8, color: "var(--text)", padding: "8px 12px", fontSize: 13 }} />
          </div>
          <div>
            <label style={{ fontSize: 12, color: "var(--text-2)", display: "block", marginBottom: 6 }}>Senha</label>
            <input type="password" value={password} onChange={e => setPassword(e.target.value)} required
              style={{ width: "100%", background: "var(--surface-2)", border: "1px solid var(--border)",
                borderRadius: 8, color: "var(--text)", padding: "8px 12px", fontSize: 13 }} />
          </div>
          {error && <p style={{ color: "var(--red)", fontSize: 12 }}>{error}</p>}
          <button type="submit"
            style={{ background: "var(--cyan)", color: "#050d1a", border: "none", borderRadius: 8,
              padding: "10px", fontWeight: 700, fontSize: 14, cursor: "pointer", marginTop: 4 }}>
            Entrar
          </button>
        </form>
      </div>
    </main>
  )
}
```

### 4.5 Variáveis de ambiente (`bio-frontend/.env.local`)

```
NEXTAUTH_SECRET=troque-por-string-aleatoria
NEXTAUTH_URL=http://localhost:3000
```

### 4.6 Passar o token nas chamadas de API (`lib/api.ts`)

```typescript
// Substituir apiFetch para aceitar token opcional
async function apiFetch<T>(path: string, token?: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    ...init,
  })
  if (!res.ok) throw new Error(`API error ${res.status}: ${path}`)
  return res.json() as Promise<T>
}
```

---

## 5. Script de seed — criar primeiro admin

```bash
# Roda uma vez após subir a API e o banco
docker exec bio-platform-api-1 python3 -c "
from passlib.context import CryptContext
import asyncio, asyncpg

pwd = CryptContext(schemes=['bcrypt']).hash('senha-aqui')

async def main():
    conn = await asyncpg.connect('postgresql://api_user:changeme@postgres:5432/bioinformatica')
    await conn.execute(
        \"INSERT INTO users (email, name, hashed_password, role) VALUES (\$1,\$2,\$3,'admin')\",
        'admin@bioinformatica.local', 'Admin', pwd
    )
    await conn.close()
    print('Admin criado.')

asyncio.run(main())
"
```

---

## 6. Ordem de implementação sugerida

1. Criar `004_auth.sql` e rodar migration
2. Instalar libs (`python-jose`, `passlib`, `next-auth`)
3. Implementar backend: `security.py` → `auth_deps.py` → `auth.py` → registrar router
4. Criar seed do primeiro admin
5. Implementar frontend: `auth.ts` → route handler → `middleware.ts` → página de login
6. Proteger rotas gradualmente (começar pelo `create_project`)
7. Adicionar `NEXTAUTH_SECRET` e `JWT_SECRET` nos secrets do Coolify/k3s
