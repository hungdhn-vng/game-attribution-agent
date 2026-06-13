// Single-user stub — no NextAuth, no database.
// All pages/routes that previously called auth() receive this local user.

export type UserType = "regular";

export const LOCAL_USER = {
  id: "local",
  name: "You",
  email: "local@localhost",
  type: "regular" as UserType,
};

export type Session = {
  user: typeof LOCAL_USER;
};

export async function auth(): Promise<Session> {
  return { user: LOCAL_USER };
}
