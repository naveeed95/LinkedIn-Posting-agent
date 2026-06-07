"""
The Tech Tutors — LinkedIn Posting Agent

Commands:
  python run.py           — research fresh topic, generate, Discord approval, publish (used by Actions)
  python run.py --preview — generate and score without publishing or Discord
"""

import os
import sys

from logger import get_logger

log_auto = get_logger("auto")
log_startup = get_logger("startup")


def _validate_env(*required: str) -> None:
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        log_startup.warning(f"ERROR: Required env vars not set: {', '.join(missing)}")
        log_startup.info("Set these as GitHub Secrets or in your .env file.")
        sys.exit(1)

def cmd_auto(target_date: str | None = None, preview: bool = False):
    """Fully automated run for GitHub Actions — researches fresh topic daily, no plan needed."""
    if not preview:
        _validate_env("GROQ_API_KEY", "LINKEDIN_ACCESS_TOKEN", "LINKEDIN_ORG_URN")
    else:
        _validate_env("GROQ_API_KEY")
        log_auto.info("Preview mode — will generate and score but NOT publish to LinkedIn.\n")
    from agent_runner import run_agent
    run_agent(target_date=target_date, preview=preview)


def main():
    args = sys.argv[1:]
    cmd_auto(preview="--preview" in args)


if __name__ == "__main__":
    main()
