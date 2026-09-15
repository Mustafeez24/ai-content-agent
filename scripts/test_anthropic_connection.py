"""
Minimal connectivity test for the Anthropic API.

Loads ANTHROPIC_API_KEY from .env, sends a tiny request to Claude, and
reports whether the connection works. Does not print or log the key itself.

Usage:
    source venv/bin/activate
    python scripts/test_anthropic_connection.py
"""

import os
import sys

from dotenv import load_dotenv
import anthropic

TEST_MODEL = "claude-haiku-4-5"  # cheapest current model - this is just a connectivity check


def main() -> int:
    load_dotenv()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("FAILED: ANTHROPIC_API_KEY is not set.")
        print("Add it to your local .env file (see .env.example) and try again.")
        return 1

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment

    try:
        response = client.messages.create(
            model=TEST_MODEL,
            max_tokens=16,
            messages=[{"role": "user", "content": "Reply with exactly one word: OK"}],
        )
    except anthropic.AuthenticationError:
        print("FAILED: Authentication error - the API key was rejected.")
        return 1
    except anthropic.PermissionDeniedError:
        print("FAILED: Permission denied - the API key lacks access to this model.")
        return 1
    except anthropic.NotFoundError:
        print(f"FAILED: Model not found ({TEST_MODEL}).")
        return 1
    except anthropic.RateLimitError:
        print("FAILED: Rate limited. Try again in a moment.")
        return 1
    except anthropic.APIConnectionError:
        print("FAILED: Network error - could not reach the Anthropic API.")
        return 1
    except anthropic.APIStatusError as e:
        print(f"FAILED: API error (status {e.status_code}).")
        return 1

    reply_text = next(
        (block.text for block in response.content if block.type == "text"), ""
    ).strip()

    print("SUCCESS: Connected to the Anthropic API.")
    print(f"Model: {response.model}")
    print(f"Response: {reply_text!r}")
    print(
        f"Tokens used: {response.usage.input_tokens} in / "
        f"{response.usage.output_tokens} out"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
