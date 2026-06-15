export const isProductionEnvironment = process.env.NODE_ENV === "production";
export const isDevelopmentEnvironment = process.env.NODE_ENV === "development";
export const isTestEnvironment = Boolean(
  process.env.PLAYWRIGHT_TEST_BASE_URL ||
    process.env.PLAYWRIGHT ||
    process.env.CI_PLAYWRIGHT
);

export const guestRegex = /^guest-\d+$/;

// DUMMY_PASSWORD no longer needed (no auth), kept as stub for any lingering imports.
export const DUMMY_PASSWORD = "dummy_password_stub";

export const suggestions = [
  "How is my game performing this month?",
  "Which channels deliver the best ROI?",
  "What's driving new player growth?",
  "Break down my revenue by source",
];
