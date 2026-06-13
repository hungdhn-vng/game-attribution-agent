import { AppSidebar } from "@/components/chat/app-sidebar";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { LOCAL_USER } from "@/lib/auth";
import { ConversationProvider } from "@/components/gaa/conversation-store";

export default function ChatLayout({ children }: { children: React.ReactNode }) {
  return (
    <ConversationProvider>
      <SidebarProvider defaultOpen={true}>
        <AppSidebar user={LOCAL_USER} />
        <SidebarInset>{children}</SidebarInset>
      </SidebarProvider>
    </ConversationProvider>
  );
}
