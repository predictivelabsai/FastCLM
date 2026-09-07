#!/usr/bin/env python3
"""Capture a deterministic, synthetic FastCLM product walkthrough."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / "screenshots"
PORT = 5125
BASE = f"http://127.0.0.1:{PORT}"
CAPTURES = (
    "01-landing.png",
    "02-ai-assistant.png",
    "03-pdf-source.png",
    "04-skills-library.png",
    "05-skill-editor.png",
    "06-overview.png",
    "07-contract-register.png",
    "08-contract-record.png",
    "09-obligations.png",
    "10-developers.png",
    "11-landing-mobile.png",
    "12-ai-assistant-mobile.png",
    "13-team.png",
    "14-settings-security.png",
    "15-approval-governance.png",
    "16-signature-execution.png",
)
FRAMES = CAPTURES[1:10] + ("13-team.png", "14-settings-security.png", "15-approval-governance.png", "16-signature-execution.png")


def wait_for_server(process: subprocess.Popen) -> None:
    for _ in range(100):
        if process.poll() is not None:
            raise RuntimeError("FastCLM stopped before screenshot capture")
        try:
            with urllib.request.urlopen(f"{BASE}/healthz", timeout=0.5) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.1)
    raise RuntimeError("Timed out waiting for FastCLM")


def shot(page, name: str) -> None:
    page.screenshot(path=SHOTS / name, animations="disabled")


def main() -> None:
    SHOTS.mkdir(exist_ok=True)
    for frame in CAPTURES:
        (SHOTS / frame).unlink(missing_ok=True)
    data_dir = Path(tempfile.mkdtemp(prefix="fastclm-demo-"))
    env = os.environ.copy()
    env.update({
        "FASTCLM_PORT": str(PORT),
        "FASTCLM_PUBLIC_URL": BASE,
        "FASTCLM_ALLOW_TEST_AUTH": "true",
        "FASTCLM_DATA_DIR": str(data_dir),
        "FASTCLM_DB": str(data_dir / "fastclm.sqlite"),
        "FASTCLM_UPLOAD_DIR": str(data_dir / "uploads"),
        "FASTCLM_REMINDER_SCHEDULER_ENABLED": "false",
        "SIGNWELL_API_KEY": "synthetic-demo-key-not-used",
        "SIGNWELL_WEBHOOK_TOKEN": "synthetic-demo-webhook-token",
    })
    process = subprocess.Popen(
        [sys.executable, "web_app.py"], cwd=ROOT, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
    )
    try:
        wait_for_server(process)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            public = browser.new_context(viewport={"width": 1440, "height": 960}, device_scale_factor=1)
            page = public.new_page()
            page.goto(BASE, wait_until="networkidle")
            shot(page, "01-landing.png")
            public.close()

            context = browser.new_context(viewport={"width": 1440, "height": 960}, device_scale_factor=1)
            page = context.new_page()
            errors: list[str] = []
            page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
            page.goto(f"{BASE}/auth/test", wait_until="networkidle")
            page.get_by_text("tool receipts", exact=False).click()
            page.get_by_text("Quoted evidence", exact=True).click()
            shot(page, "02-ai-assistant.png")
            page.get_by_text("Open PDF", exact=True).click()
            page.locator("#pdf-overlay.open").wait_for()
            page.wait_for_timeout(1500)
            shot(page, "03-pdf-source.png")
            page.keyboard.press("Escape")

            page.goto(f"{BASE}/skills", wait_until="networkidle")
            shot(page, "04-skills-library.png")
            page.get_by_role("link", name="Contract Q&A", exact=False).click()
            shot(page, "05-skill-editor.png")
            page.goto(f"{BASE}/overview", wait_until="networkidle")
            shot(page, "06-overview.png")
            page.goto(f"{BASE}/contracts", wait_until="networkidle")
            shot(page, "07-contract-register.png")
            page.get_by_role("link", name="Cloud services master agreement", exact=False).click()
            shot(page, "08-contract-record.png")
            page.goto(f"{BASE}/obligations", wait_until="networkidle")
            shot(page, "09-obligations.png")
            page.goto(f"{BASE}/developers", wait_until="networkidle")
            shot(page, "10-developers.png")
            page.goto(f"{BASE}/team", wait_until="networkidle")
            shot(page, "13-team.png")
            page.goto(f"{BASE}/settings", wait_until="networkidle")
            page.get_by_text("Source retention", exact=True).scroll_into_view_if_needed()
            page.mouse.wheel(0, 900)
            page.wait_for_timeout(200)
            shot(page, "14-settings-security.png")
            page.goto(f"{BASE}/approval-policies", wait_until="networkidle")
            shot(page, "15-approval-governance.png")
            page.goto(f"{BASE}/contracts", wait_until="networkidle")
            page.get_by_role("link", name="EU data processing agreement", exact=False).click()
            page.get_by_text("Electronic signature", exact=True).scroll_into_view_if_needed()
            page.mouse.wheel(0, 900)
            page.wait_for_timeout(200)
            shot(page, "16-signature-execution.png")

            mobile_public = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=1)
            mobile_page = mobile_public.new_page()
            mobile_page.goto(BASE, wait_until="networkidle")
            shot(mobile_page, "11-landing-mobile.png")
            mobile_public.close()
            mobile = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=1)
            mobile_page = mobile.new_page()
            mobile_page.goto(f"{BASE}/auth/test", wait_until="networkidle")
            shot(mobile_page, "12-ai-assistant-mobile.png")
            mobile.close()
            browser.close()
            if errors:
                raise RuntimeError("Browser console errors: " + " | ".join(errors))
        (SHOTS / "manifest.txt").write_text("\n".join(FRAMES) + "\n", encoding="utf-8")
        print(f"Captured {len(CAPTURES)} validated screenshots and {len(FRAMES)} walkthrough frames in {SHOTS}")
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        shutil.rmtree(data_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
