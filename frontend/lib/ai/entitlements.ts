import type { UserType } from "@/lib/auth";

type Entitlements = {
  maxMessagesPerHour: number;
};

export const entitlementsByUserType: Record<UserType, Entitlements> = {
  regular: {
    maxMessagesPerHour: 100,
  },
};
