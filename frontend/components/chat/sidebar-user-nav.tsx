"use client";

import { ChevronUp } from "lucide-react";
import { useTheme } from "next-themes";
import { useState, useEffect } from "react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { LOCAL_USER } from "@/lib/auth";

type LocalUser = {
  id?: string;
  name?: string | null;
  email?: string | null;
};

function emailToHue(email: string): number {
  let hash = 0;
  for (const char of email) {
    hash = char.charCodeAt(0) + ((hash << 5) - hash);
  }
  return Math.abs(hash) % 360;
}

export function SidebarUserNav({ user }: { user: LocalUser }) {
  const { setTheme, resolvedTheme } = useTheme();
  const email = user?.email ?? LOCAL_USER.email;

  const [admin, setAdmin] = useState(false);
  const [open, setOpen] = useState(false);
  const [pass, setPass] = useState("");
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/admin/status")
      .then((r) => r.json())
      .then((d) => setAdmin(Boolean(d.admin)))
      .catch(() => {});
  }, []);

  async function unlock() {
    const r = await fetch("/api/admin/unlock", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ passphrase: pass }),
    });
    if (r.ok) {
      setAdmin(true);
      setOpen(false);
      setPass("");
      setErr(null);
    } else {
      setErr("Incorrect passphrase");
    }
  }

  async function lock() {
    await fetch("/api/admin/unlock", { method: "DELETE" });
    setAdmin(false);
  }

  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <SidebarMenuButton
              className="h-8 px-2 rounded-lg bg-transparent text-sidebar-foreground/70 transition-colors duration-150 hover:text-sidebar-foreground data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground"
              data-testid="user-nav-button"
            >
              <div
                className="size-5 shrink-0 rounded-full ring-1 ring-sidebar-border/50"
                style={{
                  background: `linear-gradient(135deg, oklch(0.35 0.08 ${emailToHue(email)}), oklch(0.25 0.05 ${emailToHue(email) + 40}))`,
                }}
              />
              <span className="truncate text-[13px]" data-testid="user-email">
                {user?.name ?? email}
              </span>
              <ChevronUp className="ml-auto size-3.5 text-sidebar-foreground/50" />
            </SidebarMenuButton>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            className="w-(--radix-popper-anchor-width) rounded-lg border border-border/60 bg-card/95 backdrop-blur-xl shadow-[var(--shadow-float)]"
            data-testid="user-nav-menu"
            side="top"
          >
            <DropdownMenuItem
              className="cursor-pointer text-[13px]"
              data-testid="user-nav-item-theme"
              onSelect={() =>
                setTheme(resolvedTheme === "dark" ? "light" : "dark")
              }
            >
              {`Toggle ${resolvedTheme === "light" ? "dark" : "light"} mode`}
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            {admin ? (
              <DropdownMenuItem
                className="cursor-pointer text-[13px]"
                data-testid="user-nav-item-admin"
                onSelect={() => lock()}
              >
                🔓 Lock admin tools
              </DropdownMenuItem>
            ) : (
              <DropdownMenuItem
                className="cursor-pointer text-[13px]"
                data-testid="user-nav-item-admin"
                onSelect={(e) => {
                  e.preventDefault();
                  setOpen(true);
                }}
              >
                🔒 Unlock admin tools…
              </DropdownMenuItem>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogContent className="sm:max-w-sm">
            <DialogHeader>
              <DialogTitle>Unlock admin tools</DialogTitle>
              <DialogDescription>
                Enter the admin passphrase to enable exec / browse / self-edit
                and config changes for this session.
              </DialogDescription>
            </DialogHeader>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                unlock();
              }}
              className="flex flex-col gap-2"
            >
              <Input
                type="password"
                autoFocus
                placeholder="Admin passphrase"
                value={pass}
                onChange={(e) => setPass(e.target.value)}
              />
              {err && <p className="text-sm text-red-500">{err}</p>}
              <DialogFooter>
                <Button type="submit">Unlock</Button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>
      </SidebarMenuItem>
    </SidebarMenu>
  );
}
