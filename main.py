import os
import secrets
from fastapi import FastAPI
from pydantic import BaseModel
from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright

app = FastAPI()

# Setup template env
env = Environment(loader=FileSystemLoader("templates"))


class CardData(BaseModel):
    amount: str
    merchant_name: str
    time_str: str


def html_to_image(html_content: str, output: str):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(
            viewport={"width": 1920, "height": 1080},
            device_scale_factor=5.0,  # High-DPI scaling
        )
        page.set_content(html_content)
        card = page.query_selector(".card")
        if card:
            card.screenshot(path=output)
            print(f"✅ Cropped card saved as {output}")
        else:
            # fallback: full page
            page.screenshot(path=output, full_page=True)
            print("⚠️ Card not found, saved full page.")

        browser.close()


@app.post("/generate-payment-card")
def generate_card(data: CardData):
    template = env.get_template("payment_paid_card_template.html")
    html_content = template.render(
        amount=data.amount,
        time_str=data.time_str,
        merchant_name=data.merchant_name,
    )

    # Generate unique filename
    filename = f"payment_paid_card_{secrets.token_hex(4)}.png"
    filepath = os.path.join("generated", filename)

    # Render HTML → PNG using Playwright
    html_to_image(html_content, filepath)

    return {"status": "success", "file_path": filepath}
