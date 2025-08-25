import os
import secrets
import requests
from pydantic import BaseModel
from dotenv import load_dotenv
from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright
from fastapi import FastAPI, Request, HTTPException

# Load .env
load_dotenv()

app = FastAPI()

# Setup template env
env = Environment(loader=FileSystemLoader("templates"))

# Allowed IPs from .env (comma-separated)
allowed_ips = os.getenv("ALLOWED_IPS", "")
allowed_ips = [ip.strip() for ip in allowed_ips.split(",") if ip.strip()]  # list


class CardData(BaseModel):
    amount: str
    chat_id: str
    time_str: str
    apiToken: str
    instance_id: str
    merchant_name: str
    merchant_phone: str
    product_owner_phone: str


# ----------------------------
# Middleware: Restrict by IP
# ----------------------------
@app.middleware("http")
async def ip_restrict_middleware(request: Request, call_next):
    client_ip = request.client.host
    if allowed_ips:  # if list not empty, enforce restriction
        if client_ip not in allowed_ips:
            raise HTTPException(status_code=403, detail="Access denied")
    response = await call_next(request)
    return response


# ----------------------------
# HTML → Image (Card only)
# ----------------------------
def html_to_image(html_content: str, output: str):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(
            viewport={"width": 1920, "height": 1080},
            device_scale_factor=3.0,  # high quality scaling
        )
        page.set_content(html_content)

        # Screenshot only the card
        card = page.query_selector(".card")
        if card:
            card.screenshot(path=output)
            print(f"✅ Cropped card saved as {output}")
        else:
            page.screenshot(path=output, full_page=True)
            print("⚠️ Card not found, saved full page.")

        browser.close()


# ----------------------------
# WhatsApp Sender
# ----------------------------
def send_whatsapp_image(image_path, chat_id, instance_id, apiToken):
    url = f"https://7105.media.greenapi.com/waInstance{instance_id}/sendFileByUpload/{apiToken}"
    payload = {
        "chatId": f"92{chat_id}@c.us",
        "caption": "",
    }
    with open(image_path, "rb") as f:
        files = [("file", (os.path.basename(image_path), f, "image/jpeg"))]
        response = requests.post(url, data=payload, files=files)

    print("✅ WhatsApp API response:", response.text)
    return response.json()


# ----------------------------
# Main Endpoint
# ----------------------------
@app.post("/generate-payment-card")
def generate_card(data: CardData):
    template = env.get_template("payment_paid_card_template.html")
    html_content = template.render(
        amount=data.amount,
        time_str=data.time_str,
        merchant_name=data.merchant_name,
        merchant_phone=data.merchant_phone,
        product_owner_phone=data.product_owner_phone,
    )

    # Generate unique filename
    os.makedirs("generated", exist_ok=True)
    filename = f"payment_paid_card_{secrets.token_hex(4)}.png"
    filepath = os.path.join("generated", filename)

    # Render HTML → PNG
    html_to_image(html_content, filepath)

    # Send via WhatsApp
    response = send_whatsapp_image(
        filepath, data.chat_id, data.instance_id, data.apiToken
    )
    if os.path.exists(filepath):
        os.remove(filepath)

    return {
        "status": "success",
        "file_path": filepath,
        "whatsapp_response": response,
    }
