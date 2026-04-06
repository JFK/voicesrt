"""E2E smoke tests for VoiceSRT critical UI flows."""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def test_setup_wizard(page: Page, base_url: str):
    """Fresh app (no API keys) redirects to /setup, wizard flows through 3 steps."""
    page.goto(base_url + "/")
    # Should redirect to setup since no API keys are configured
    page.wait_for_url("**/setup")

    # Step 1: Choose provider — two provider buttons visible
    openai_btn = page.locator("button", has_text="OpenAI")
    google_btn = page.locator("button", has_text="Google")
    expect(openai_btn).to_be_visible()
    expect(google_btn).to_be_visible()

    # Click OpenAI provider
    openai_btn.click()

    # Step 2: Enter API key — input and save button visible
    key_input = page.locator('input[type="password"]')
    expect(key_input).to_be_visible()

    save_button = page.locator("button", has_text="Save")
    expect(save_button).to_be_visible()

    # Verify back button works — returns to step 1
    page.locator("button", has_text="Back").click()
    expect(openai_btn).to_be_visible()


def test_settings_page(page: Page, base_url: str):
    """Settings page loads with API key section and model dropdowns."""
    page.goto(base_url + "/settings")

    # Page heading
    heading = page.locator("h1")
    expect(heading).to_be_visible()
    expect(heading).to_contain_text("Settings")

    # API Keys section
    expect(page.locator("text=API Keys")).to_be_visible()

    # Ollama section should exist (static h2, not Alpine-rendered)
    expect(page.locator("h2", has_text="Ollama")).to_be_visible()

    # API key input fields are rendered (via Alpine.js template loop)
    page.wait_for_function("document.querySelectorAll('input[type=password]').length > 0")
    key_inputs = page.locator('input[type="password"]')
    expect(key_inputs.first).to_be_visible()


def test_upload_page_form(page: Page, base_url: str):
    """Upload page form elements are interactive (requires API key to be set)."""
    # First set an API key so upload page doesn't redirect to setup
    page.request.put(
        base_url + "/api/settings/keys/openai",
        data={"key": "sk-test-fake-key-for-e2e-testing-only"},
    )

    page.goto(base_url + "/upload")
    page.wait_for_url("**/upload")

    # Page heading
    heading = page.locator("h1")
    expect(heading).to_be_visible()
    expect(heading).to_contain_text("Upload")

    # Provider select
    provider_select = page.locator('select[x-model="provider"]')
    expect(provider_select).to_be_visible()
    provider_select.select_option("gemini")
    expect(provider_select).to_have_value("gemini")

    # Language select
    lang_select = page.locator('select[x-model="language"]')
    expect(lang_select).to_be_visible()
    lang_select.select_option("ja")
    expect(lang_select).to_have_value("ja")

    # Enable refine checkbox — toggles post-processing section
    refine_checkbox = page.locator("#enableRefine")
    expect(refine_checkbox).to_be_visible()
    refine_checkbox.check()
    expect(refine_checkbox).to_be_checked()

    # Post-processing model section appears
    pp_provider = page.locator('select[x-model="ppProvider"]')
    expect(pp_provider).to_be_visible()


def test_navigation(page: Page, base_url: str):
    """Nav links work and page headings render correctly."""
    pages = [
        ("/settings", "Settings"),
        ("/history", "History"),
        ("/costs", "Cost"),
    ]

    for path, expected_text in pages:
        page.goto(base_url + path)
        heading = page.locator("h1")
        expect(heading).to_be_visible()
        expect(heading).to_contain_text(expected_text)

    # Nav bar links are present
    page.goto(base_url + "/settings")
    nav = page.locator("nav")
    expect(nav.get_by_role("link", name="VoiceSRT")).to_be_visible()
    expect(nav.locator('a[href="/history"]')).to_be_visible()
    expect(nav.locator('a[href="/costs"]')).to_be_visible()
    expect(nav.locator('a[href="/settings"]')).to_be_visible()


def test_language_switch(page: Page, base_url: str):
    """Language switch EN ↔ JA changes page headings."""
    page.goto(base_url + "/settings")
    heading = page.locator("h1")

    # Default should be English
    expect(heading).to_contain_text("Settings")

    # Switch to Japanese
    page.locator('a[href="/lang/ja"]').click()
    page.wait_for_load_state("networkidle")
    expect(heading).to_contain_text("設定")

    # Switch back to English
    page.locator('a[href="/lang/en"]').click()
    page.wait_for_load_state("networkidle")
    expect(heading).to_contain_text("Settings")
