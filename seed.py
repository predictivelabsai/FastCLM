"""Create the idempotent synthetic FastCLM demonstration workspace."""
from fastclm.bootstrap import ensure_demo


if __name__ == "__main__":
    user, organisation = ensure_demo()
    print(f"Synthetic workspace ready: {organisation['name']} ({user['email']})")
