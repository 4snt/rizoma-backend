import NextAuth from "next-auth"
import Google from "next-auth/providers/google"

const API = process.env.API_URL ?? "http://localhost:8000"
const ALLOWED_DOMAIN = process.env.ALLOWED_EMAIL_DOMAIN ?? "@ufvjm.edu.br"
const ALLOWED_HD = ALLOWED_DOMAIN.replace("@", "")

export const { handlers, signIn, signOut, auth } = NextAuth({
  trustHost: true,
  providers: [
    Google({
      clientId: process.env.GOOGLE_CLIENT_ID!,
      clientSecret: process.env.GOOGLE_CLIENT_SECRET!,
      authorization: { params: { hd: ALLOWED_HD, prompt: "select_account" } },
    }),
  ],
  callbacks: {
    authorized({ auth: session, request }) {
      const path = request.nextUrl.pathname
      const isPublic = path.startsWith("/login") || path.startsWith("/api/auth")
      console.log("[MW] path=%s isPublic=%s session=%s", path, isPublic, session ? JSON.stringify({ role: (session as any).role, error: (session as any).error, email: (session as any).userEmail }) : null)
      if (!session && !isPublic) return false
      if (path.startsWith("/admin") && (session as any)?.role !== "admin") {
        return Response.redirect(new URL("/", request.url))
      }
      return true
    },
    async signIn({ profile }) {
      return !!profile?.email?.endsWith(ALLOWED_DOMAIN)
    },
    async jwt({ token, account }) {
      if (account?.access_token) {
        const res = await fetch(`${API}/api/v1/auth/google`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ access_token: account.access_token }),
        })
        if (res.ok) {
          const data = await res.json()
          token.accessToken = data.access_token
          token.role        = data.role
          token.userEmail   = data.email
          token.userName    = data.name
        } else {
          const errBody = await res.json().catch(() => ({}))
          console.error(`[auth] backend ${res.status}:`, JSON.stringify(errBody))
          token.error = res.status === 403 ? "NotInvited" : "AuthError"
        }
      }
      return token
    },
    async session({ session, token }) {
      session.accessToken = token.accessToken as string
      session.role        = token.role as string
      session.error       = token.error as string | undefined
      session.userEmail   = token.userEmail as string
      session.userName    = token.userName as string
      return session
    },
  },
  pages: { signIn: "/login", error: "/login" },
  secret: process.env.AUTH_SECRET ?? process.env.NEXTAUTH_SECRET,
})
