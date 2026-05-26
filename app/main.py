import os
import shutil
import requests
from typing import Optional
from fastapi import FastAPI, UploadFile, Form, HTTPException, File, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
from dotenv import load_dotenv

load_dotenv()

EXTERNAL_BACKEND_URL = os.getenv("EXTERNAL_BACKEND_URL", "")

from app.extractor import extract_text, generate_uk_restaurant_prompt
from app.vapi_client import create_assistant, link_telephony

from app.business_store import save_business_config, get_business_config

def parse_single_string_item(item_str: str) -> dict:
    import re
    item_str = item_str.strip()
    match = re.match(r"^(\d+)\s*x?\s*(.+)$", item_str, re.IGNORECASE)
    if match:
        quantity = match.group(1)
        product_name = match.group(2).strip()
        return {
            "product_name": product_name,
            "quantity": quantity,
            "unit_prize": "0.0"
        }
    return {
        "product_name": item_str,
        "quantity": "1",
        "unit_prize": "0.0"
    }

def normalize_list(items) -> list:
    normalized = []
    if not isinstance(items, list):
        items = [items]
    for item in items:
        if isinstance(item, dict):
            product_name = item.get("product_name") or item.get("name") or item.get("item") or "Unknown Product"
            quantity = item.get("quantity") or item.get("qty") or item.get("count") or "1"
            unit_prize = item.get("unit_prize") or item.get("unit_price") or item.get("price")
            
            if unit_prize is not None:
                unit_prize = str(unit_prize)
            else:
                unit_prize = "0.0"

            normalized.append({
                "product_name": str(product_name),
                "quantity": str(quantity),
                "unit_prize": str(unit_prize)
            })
        elif isinstance(item, str):
            parsed_item = parse_single_string_item(item)
            if parsed_item:
                normalized.append(parsed_item)
    return normalized

def parse_and_format_order_details(order_items, total_price) -> list:
    """
    Parses and formats order_items into the user's requested schema:
    [
        {
            "product_name": str,
            "quantity": str,
            "unit_prize": str
        }
    ]
    """
    if not order_items:
        return []

    # Case 1: If order_items is a string, try to parse it as JSON first
    if isinstance(order_items, str):
        cleaned = order_items.strip()
        if (cleaned.startswith("{") and cleaned.endswith("}")) or (cleaned.startswith("[") and cleaned.endswith("]")):
            try:
                import json
                parsed = json.loads(cleaned)
                if isinstance(parsed, dict) and "order_details" in parsed:
                    return normalize_list(parsed["order_details"])
                if isinstance(parsed, dict):
                    return normalize_list([parsed])
                if isinstance(parsed, list):
                    return normalize_list(parsed)
            except Exception:
                pass

    # Case 2: If it is already a dictionary
    if isinstance(order_items, dict):
        if "order_details" in order_items:
            return normalize_list(order_items["order_details"])
        return normalize_list([order_items])

    # Case 3: If it is already a list
    if isinstance(order_items, list):
        return normalize_list(order_items)

    # Case 4: Unstructured string fallback (e.g., "2x Cola, 2x pizza")
    parsed_items = []
    if isinstance(order_items, str):
        parts = [p.strip() for p in order_items.replace("\n", ",").split(",") if p.strip()]
        for part in parts:
            parsed_item = parse_single_string_item(part)
            if parsed_item:
                parsed_items.append(parsed_item)
    
    import os
    openai_key = os.getenv("OPENAI_API_KEY", "")
    if openai_key and parsed_items:
        try:
            import openai
            client = openai.OpenAI(api_key=openai_key)
            prompt = f"""
            You are an expert order parser. Convert the following unstructured order items string and total price into a clean, structured JSON list of objects.
            
            Order items string: "{order_items}"
            Total Price of the entire order: {total_price}
            
            For each item, extract:
            - "product_name": Name of the item (e.g. "Cola", "Pepperoni Pizza").
            - "quantity": Number ordered as a string (e.g. "2").
            - "unit_prize": Price of ONE unit of this item as a string (e.g. "3.5"). If you cannot calculate it, guess a reasonable value based on the total price and items, but make sure the sum of (quantity * unit_prize) roughly equals the total price.
            
            Respond ONLY with a valid JSON array of objects, like this:
            [
                {{"product_name": "Cola", "quantity": "2", "unit_prize": "3.5"}},
                {{"product_name": "pizza", "quantity": "2", "unit_prize": "21.5"}}
            ]
            Do not include any markdown backticks, explanations, or comments.
            """
            
            response = client.chat.completions.create(
                model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0
            )
            content = response.choices[0].message.content.strip()
            
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip("` \n")
                
            import json
            parsed = json.loads(content)
            if isinstance(parsed, list):
                return normalize_list(parsed)
        except Exception as e:
            print(f"⚠️ OpenAI parsing failed, using regex fallback: {str(e)}")
            
    return parsed_items

app = FastAPI(title="Vapi AI Microservice")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs("uploads", exist_ok=True)

class TelephonyLinkRequest(BaseModel):
    assistant_id: str
    twilio_number: str
    manager_number: str

class SpecialOffersUpdateRequest(BaseModel):
    enabled: bool
    special_offers_text: Optional[str] = None

@app.post("/api/agents/create")
async def create_agent(
    business_id: str = Form(...),
    rules_file: UploadFile = File(...),
    menu_file: UploadFile = File(...),
    special_offers_text: str = Form(""),
    special_offers_file: Optional[UploadFile] = File(None),
    special_offers_enabled: bool = Form(True)
):
    """
    Creates or updates a Vapi assistant.
    Special offers are optional.
    The extracted rules/menu/offers are saved so they can be reused later when toggling offers on/off.
    """
    saved_paths = []

    try:
        rules_path = f"uploads/{business_id}_rules_{rules_file.filename}"
        menu_path = f"uploads/{business_id}_menu_{menu_file.filename}"

        saved_paths.extend([rules_path, menu_path])

        with open(rules_path, "wb") as buffer:
            shutil.copyfileobj(rules_file.file, buffer)

        with open(menu_path, "wb") as buffer:
            shutil.copyfileobj(menu_file.file, buffer)

        rules_text = extract_text(rules_path)
        menu_text = extract_text(menu_path)

        offers_parts = []

        if special_offers_text and special_offers_text.strip():
            offers_parts.append(special_offers_text.strip())

        if special_offers_file and special_offers_file.filename:
            offers_path = f"uploads/{business_id}_special_offers_{special_offers_file.filename}"
            saved_paths.append(offers_path)

            with open(offers_path, "wb") as buffer:
                shutil.copyfileobj(special_offers_file.file, buffer)

            extracted_offers = extract_text(offers_path).strip()

            if extracted_offers:
                offers_parts.append(extracted_offers)

        saved_special_offers_text = "\n".join(offers_parts).strip()

        active_special_offers_text = (
            saved_special_offers_text
            if special_offers_enabled and saved_special_offers_text
            else ""
        )

        system_prompt = generate_uk_restaurant_prompt(
            rules_text,
            menu_text,
            special_offers_text=active_special_offers_text
        )

        vapi_response = create_assistant(business_id, system_prompt)

        save_business_config(
            business_id,
            {
                "business_id": business_id,
                "rules_text": rules_text,
                "menu_text": menu_text,
                "special_offers_enabled": special_offers_enabled,
                "special_offers_text": saved_special_offers_text,
                "assistant_id": vapi_response.get("id")
            }
        )

        return {
            "status": "success",
            "business_id": business_id,
            "assistant_id": vapi_response.get("id"),
            "special_offers_enabled": special_offers_enabled,
            "special_offers_active_in_prompt": bool(active_special_offers_text),
            "message": "Agent created or updated successfully.",
            "vapi_response": vapi_response
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        for path in saved_paths:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass


@app.patch("/api/agents/{business_id}/special-offers")
async def update_special_offers(
    business_id: str,
    request: SpecialOffersUpdateRequest
):
    """
    Turns special offers on or off.
    This regenerates the full system prompt and updates the existing Vapi assistant.
    """
    try:
        config = get_business_config(business_id)

        if not config:
            raise HTTPException(
                status_code=404,
                detail="Business config not found. Create the agent first using /api/agents/create."
            )

        current_saved_offers = config.get("special_offers_text", "").strip()

        # If special_offers_text is provided, update the saved offer text.
        # If it is not provided, keep the previous saved offer text.
        if request.special_offers_text is not None:
            saved_special_offers_text = request.special_offers_text.strip()
        else:
            saved_special_offers_text = current_saved_offers

        # This is the important part.
        # If enabled is false, active_special_offers_text becomes empty.
        # Then generate_uk_restaurant_prompt() inserts "No active special offers..."
        active_special_offers_text = (
            saved_special_offers_text
            if request.enabled and saved_special_offers_text
            else ""
        )

        system_prompt = generate_uk_restaurant_prompt(
            config["rules_text"],
            config["menu_text"],
            special_offers_text=active_special_offers_text
        )

        # Your create_assistant() already PATCHES the existing Vapi assistant
        # if it finds the same business_id.
        vapi_response = create_assistant(business_id, system_prompt)

        config["special_offers_enabled"] = request.enabled
        config["special_offers_text"] = saved_special_offers_text
        config["assistant_id"] = vapi_response.get("id")

        save_business_config(business_id, config)

        return {
            "status": "success",
            "business_id": business_id,
            "assistant_id": vapi_response.get("id"),
            "special_offers_enabled": request.enabled,
            "special_offers_active_in_prompt": bool(active_special_offers_text),
            "message": (
                "Special offers are now enabled in the assistant prompt."
                if request.enabled
                else "Special offers are now removed from the assistant prompt."
            )
        }

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
    
@app.post("/api/telephony/link")
async def link_phone(request: TelephonyLinkRequest):
    """
    Links a Twilio phone number to a specific Vapi assistant.
    Also records the manager_number (can be used for call transfers later).
    """
    try:
        response = link_telephony(
            assistant_id=request.assistant_id,
            twilio_number=request.twilio_number,
            manager_number=request.manager_number
        )
        
        return {
            "status": "success",
            "message": "Telephony linked successfully.",
            "vapi_response": response
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- VAPI WEBHOOKS (MOVED FROM MOCK BACKEND) ---

def forward_order_task(business_id: str, assistant_id: str, args: dict):
    """Runs in the background to prevent Vapi tool timeouts"""
    if EXTERNAL_BACKEND_URL:
        try:
            # Parse and format the order items safely in the background
            order_details = parse_and_format_order_details(args.get("order_items"), args.get("total_price"))
            
            forward_payload = {
                "assistantId": assistant_id,
                "business_id": business_id,
                "customer_name": args.get("customer_name"),
                "customer_email": args.get("customer_email"),
                "order_items": args.get("order_items"),  # KEEP original key for backward compatibility
                "order_details": order_details,          # ADD new requested JSON format
                "items": order_details,                  # ADD items key matching user requested schema
                "total_price": args.get("total_price"),
                "source": "vapi_voice_agent"
            }
            requests.post(EXTERNAL_BACKEND_URL, json=forward_payload, timeout=5)
            print(f"✅ Order forwarded to {EXTERNAL_BACKEND_URL}")
        except Exception as e:
            print(f"❌ Failed to forward order: {str(e)}")


@app.post("/webhook/order")
async def handle_order(request: Request, background_tasks: BackgroundTasks):
    """Receives the LIVE ORDER tool call from Vapi"""
    body = await request.body()
    if not body:
        return {"status": "error", "message": "Empty request body"}
    
    data = await request.json()
    
    # DEBUG: Print raw data to see exactly what Vapi sends
    # print(f"DEBUG ORDER DATA: {data}")

    # For apiRequest tools, Vapi sends the arguments directly in the root or inside 'message'
    if "customer_name" in data:
        # This is a flat apiRequest tool call
        args = data
        business_id = "Dashboard Tool"
        assistant_id = "Unknown" # Flat API requests usually don't send this outside headers
        import json
        formatted_details = parse_and_format_order_details(args.get("order_items"), args.get("total_price"))
        print(f"\n--- 🍕 NEW ORDER RECEIVED for {business_id} ---")
        print(f"Customer: {args.get('customer_name')}")
        print(f"Email: {args.get('customer_email')}")
        print(f"Items (Raw): {args.get('order_items')}")
        print(f"Items (Structured JSON): {json.dumps({'order_details': formatted_details}, indent=2)}")
        print(f"Total: £{args.get('total_price')}")
        print("-------------------------------------------\n")

        # Forward in background to avoid blocking Vapi
        background_tasks.add_task(forward_order_task, business_id, assistant_id, args)

        # Return explicit instructions to the LLM
        return {
            "status": "success", 
            "result": "Order saved successfully. The kitchen has received the order. Immediately inform the customer their order is confirmed and politely say goodbye to end the call."
        }

    else:
        # This is a Vapi Server tool call
        message = data.get("message", {})
        
        # Extract assistant ID from the server tool payload
        call_data = message.get("call", {})
        assistant_id = call_data.get("assistantId", "Unknown")
        
        # Vapi might send 'toolCalls' or 'toolWithToolCallList' depending on the API version
        tool_calls = message.get("toolCalls", [])
        if not tool_calls and "toolWithToolCallList" in message:
            for item in message.get("toolWithToolCallList", []):
                if "toolCall" in item:
                    tool_calls.append(item["toolCall"])
        
        results = []
        for tool_call in tool_calls:
            args = tool_call.get("function", {}).get("arguments", {})
            
            # OpenAI/Vapi often send arguments as a JSON string
            if isinstance(args, str):
                import json
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}
            business_id = message.get("customer", {}).get("metadata", {}).get("business_id", "Unknown")

            import json
            formatted_details = parse_and_format_order_details(args.get("order_items"), args.get("total_price"))
            print(f"\n--- 🍕 NEW ORDER RECEIVED for {business_id} ---")
            print(f"Assistant ID: {assistant_id}")
            print(f"Customer: {args.get('customer_name')}")
            print(f"Email: {args.get('customer_email')}")
            print(f"Items (Raw): {args.get('order_items')}")
            print(f"Items (Structured JSON): {json.dumps({'order_details': formatted_details}, indent=2)}")
            print(f"Total: £{args.get('total_price')}")
            print("-------------------------------------------\n")

            # Forward in background to avoid blocking Vapi
            background_tasks.add_task(forward_order_task, business_id, assistant_id, args)

            # Return explicit instructions to the LLM
            results.append({
                "toolCallId": tool_call.get("id"),
                "result": "Order saved successfully. The kitchen has received the order. Immediately inform the customer their order is confirmed and politely say goodbye to end the call."
            })
            
        return {"results": results}

@app.post("/webhook/summary")
async def handle_summary(request: Request):
    """Receives the POST-CALL summary from Vapi"""
    data = await request.json()
    
    message = data.get("message", {})
    msg_type = data.get("type") or message.get("type")
    
    # Only process 'end-of-call-report' or 'status-update' that actually has a summary
    call_data = message.get("call", data.get("call", {}))
    analysis = call_data.get("analysis", {})
    summary = analysis.get("summary")

    if not summary:
        return {"status": "ignored", "reason": "no summary in this packet"}

    business_id = call_data.get("metadata", {}).get("business_id", "Unknown")
    structured_data = analysis.get("structuredData")

    print(f"\n--- 📝 FINAL CALL SUMMARY for {business_id} ---")
    print(f"AI Summary: {summary}")
    if structured_data:
        import json
        print(f"Structured Data: {json.dumps(structured_data, indent=2)}")
    print(f"Transcript Snippet: {call_data.get('transcript', '')[:100]}...")
    print("------------------------------------------\n")

    return {"status": "received"}


@app.post("/api/webhook/vapi")
async def vapi_tool_fallback(request: Request, background_tasks: BackgroundTasks):
    """Central Webhook Router for Vapi (Receives Tools, Summaries, and Status Updates)"""
    try:
        data = await request.json()
    except Exception:
        return {"status": "error", "message": "Invalid JSON"}

    message = data.get("message", {})
    msg_type = message.get("type", data.get("type", ""))

    if msg_type == "tool-calls" or "toolCalls" in message or "toolWithToolCallList" in message or "customer_name" in data:
        # Route to Order Logic
        return await handle_order(request, background_tasks)
    elif msg_type in ["end-of-call-report", "status-update", "hang-up"]:
        # Route to Summary Logic
        return await handle_summary(request)
    else:
        return {"status": "ignored", "reason": f"Unhandled message type: {msg_type}"}


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
