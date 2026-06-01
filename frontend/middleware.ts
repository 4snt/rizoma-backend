import { NextRequest, NextResponse } from "next/server"
import { getToken } from "next-auth/jwt"

export async function middleware(req: NextRequest) {
  const token = await getToken({
    req,
    secret: process.env.AUTH_SECRET ?? process.env.NEXTAUTH_SECRET,
  })

  const path = req.nextUrl.pathname
  const isPublic = path.startsWith("/login") || path.startsWith("/api/auth")

  if (!token && !isPublic) {
    return NextResponse.redirect(new URL("/login", req.url))
  }

  if (path.startsWith("/admin") && token?.role !== "admin") {
    return NextResponse.redirect(new URL("/", req.url))
  }
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
}
