import re

_SETUP_HINTS = ("connect", "onboard", "upload", "set up", "setup", "add my data", "csv", "import")

# Greeting words: matched only as the leading token of a short message (so "hi" in
# "this" or "high" never triggers, and "hi, what can you do?" is caught by a help phrase).
_GREETINGS = {"hi", "hello", "hey", "yo", "hiya", "howdy", "hallo", "greetings",
              "gm", "thanks", "thank"}

# Capability / "what is this" questions — matched as substrings.
_HELP_PHRASES = (
    "what can you do", "what do you do", "what can this do", "what can you help",
    "who are you", "what are you", "what is this", "what's this",
    "how do you work", "how does this work", "how do i use",
    "what can i ask", "what should i ask", "your capabilities", "capabilities",
    "getting started", "get started", "what can i do here",
)


def _looks_like_help(m: str) -> bool:
    """A greeting or a question about the agent's capabilities — not an analysis request."""
    stripped = m.strip().strip("?.! ")
    if stripped in ("help", "?", ""):
        return True
    if any(p in m for p in _HELP_PHRASES):
        return True
    words = re.findall(r"[a-z']+", m)
    if words and words[0] in _GREETINGS and len(words) <= 4:
        return True
    return False


def classify_intent(message: str, has_active_profile: bool) -> str:
    m = message.lower()
    if any(h in m for h in _SETUP_HINTS):
        return "setup"
    if not has_active_profile:
        return "setup"   # nothing to analyze yet — guide to onboarding
    if _looks_like_help(m):
        return "help"    # greeting / capability question — don't run a full analysis
    return "analyze"
