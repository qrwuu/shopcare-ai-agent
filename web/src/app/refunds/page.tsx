"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

export default function RefundsRedirectPage() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/after-sales");
  }, [router]);
  return null;
}
