_SETUP_HINTS = ("connect", "onboard", "upload", "set up", "setup", "add my data", "csv", "import")


def classify_intent(message: str, has_active_profile: bool) -> str:
    m = message.lower()
    if any(h in m for h in _SETUP_HINTS):
        return "setup"
    if not has_active_profile:
        return "setup"   # nothing to analyze yet
    return "analyze"
