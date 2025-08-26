import os
import secrets
import logging
import requests

from pydantic import BaseModel
from dotenv import load_dotenv
from fastapi.responses import JSONResponse
from playwright.sync_api import sync_playwright
from jinja2 import Environment, FileSystemLoader
from fastapi import FastAPI, Request, BackgroundTasks

# Load .env
load_dotenv()
app = FastAPI()
logger = logging.getLogger("uvicorn.error")

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
    is_1bill: bool
    instance_id: str
    merchant_name: str
    merchant_phone: str
    transaction_id: str
    product_owner_phone: str


# ----------------------------
# Middleware: Restrict by IP
# ----------------------------
@app.middleware("http")
async def ip_restrict_middleware(request: Request, call_next):
    client_ip = request.client.host
    if allowed_ips:  # if list not empty, enforce restriction
        logger.info(f"Allowed Ips: {allowed_ips}")
        if client_ip not in allowed_ips:
            logger.warning(f"Access denied for IP: {client_ip}")
            return JSONResponse(
                status_code=403,
                content={"detail": f"Access denied for your IP: {client_ip}"},
            )
        logger.info(f"Ip check passed for Ip: {client_ip}")
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
            logger.info(f"✅ Cropped card saved as {output}")
        else:
            page.screenshot(path=output, full_page=True)
            logger.warning(f"⚠️ Card not found, saved full page as {output}")

        browser.close()


# ----------------------------
# WhatsApp Sender
# ----------------------------
def send_whatsapp_image(image_path, chat_id, instance_id, apiToken):
    url = f"https://7700.media.greenapi.com/waInstance{instance_id}/sendFileByUpload/{apiToken}"
    payload = {
        "chatId": f"92{chat_id}@c.us",
        "caption": "",
    }
    with open(image_path, "rb") as f:
        files = [("file", (os.path.basename(image_path), f, "image/jpeg"))]
        response = requests.post(url, data=payload, files=files)

    logger.info(f"✅ WhatsApp API response: {response.text}")
    try:
        return response.json()
    except ValueError:  # not JSON
        return {
            "error": "Non-JSON response",
            "status": response.status_code,
            "text": response.text,
        }


# ----------------------------
# Background Task
# ----------------------------
def process_card(data: CardData, filepath: str):
    # Render HTML template
    template = env.get_template("payment_paid_card_template.html")
    html_content = template.render(
        amount=data.amount,
        time_str=data.time_str,
        is_1bill=data.is_1bill,
        merchant_name=data.merchant_name,
        merchant_phone=data.merchant_phone,
        transaction_id=data.transaction_id,
        product_owner_phone=data.product_owner_phone,
    )

    # Render HTML → PNG
    html_to_image(html_content, filepath)

    # Send via WhatsApp
    try:
        send_whatsapp_image(filepath, data.chat_id, data.instance_id, data.apiToken)
    finally:
        if os.path.exists(filepath):
            os.remove(filepath)


# ----------------------------
# Main Endpoint
# ----------------------------
@app.post("/generate-payment-card")
def generate_card(data: CardData, background_tasks: BackgroundTasks):
    os.makedirs("generated", exist_ok=True)
    filename = f"payment_paid_card_{secrets.token_hex(4)}.png"
    filepath = os.path.join("generated", filename)

    # Queue background task
    background_tasks.add_task(process_card, data, filepath)

    # Return immediate response
    return {"status": "queued", "file_path": filepath}
