import Link from "next/link";
import { headers } from "next/headers";
import { redirect } from "next/navigation";
import type { Metadata } from "next";
import { AuthPanel } from "@/components/auth-panel";
import { auth } from "@/lib/auth";
import { resolveReturnTo } from "@/lib/return-to";

export const metadata: Metadata = {
  title: "登录 · CocoCV",
  description: "登录以继续使用 CocoCV",
};

type AccountPageProps = {
  searchParams: Promise<{
    returnTo?: string | string[];
  }>;
};

export default async function AccountPage({ searchParams }: AccountPageProps) {
  const params = await searchParams;
  const returnTo = resolveReturnTo(params.returnTo);
  const session = await auth.api.getSession({
    headers: await headers(),
  });

  // 已登录：鉴权层只作登录 / OAuth 桥，直接服务端跳回应用，
  // 不再渲染“账户与权益中心”面板，消除登录后的页面闪现。
  if (session) {
    redirect(returnTo);
  }

  return (
    <main className="auth-screen">
      <AuthPanel returnTo={returnTo} />
      <Link href="/" className="auth-screen-home">
        ← 返回首页
      </Link>
    </main>
  );
}
