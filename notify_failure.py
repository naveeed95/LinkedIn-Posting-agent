"""
CLI helper called by GitHub Actions failure steps.

Usage:
  python notify_failure.py --workflow-name "Daily Post" --run-url "https://..."
"""

import argparse

from dotenv import load_dotenv

load_dotenv()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workflow-name", default="Workflow", help="Human-readable workflow name")
    parser.add_argument("--run-url", default="", help="Direct URL to the GitHub Actions run")
    args = parser.parse_args()

    link = f"\n🔗 **Run:** {args.run_url}" if args.run_url else ""
    message = f"❌ **{args.workflow_name} FAILED**{link}"

    from discord_bot import notify_workflow_failure
    notify_workflow_failure(message)
    print(f"[notify] Failure notification sent: {args.workflow_name}")


if __name__ == "__main__":
    main()
