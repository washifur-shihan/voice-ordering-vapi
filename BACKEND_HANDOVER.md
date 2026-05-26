# SaaS Backend Handover & API Guide

## 📡 System Overview
This repository contains the **AI Core Microservice** for the Multi-Tenant Vapi Voice Agent SaaS. 
It acts as the bridge between your main SaaS Dashboard and Vapi.ai. 

**Architecture:** The AI operates as a completely stateless microservice. **You do not need to touch or deploy any Python code.** Your main backend (e.g. Node.js, PHP, Ruby) will simply interface with this AI engine via standard REST APIs to provision agents and link Twilio numbers.

---

## 🔌 Core API Endpoints for Backend Integration

To build the SaaS Dashboard, you will exclusively use the following endpoints exposed by this FastAPI Microservice (Running on `http://localhost:8000` by default):

### 1. Onboarding a Business (Create Agent): `POST /api/agents/create`
- **Purpose:** When a business user signs up and uploads their rules/menu on your dashboard, send those files here via `multipart/form-data`.
- **Required Form Fields:** 
  - `business_id`: String (Your internal DB ID for the business. We inject this into Vapi so you can track it later).
  - `rules_file`: The `.pdf`, `.docx`, or `.txt` document containing the persona/greeting.
  - `menu_file`: The `.xlsx` or `.csv` document containing the menu/prices.
- **What it does:** The AI automatically extracts the text, generates a highly optimized UK-Restaurant Conversational Prompt, and calls Vapi to provision the agent. It configures the agent to automatically extract the Order Summary at the end of the call.
- **Returns:** JSON containing the unique `assistant_id`. **Save this `assistant_id` in your primary SaaS database!**

### 2. Linking Telephony: `POST /api/telephony/link`
- **Purpose:** When an admin assigns a Twilio number to a business, call this endpoint to link it.
- **Required JSON Body:**
  - `assistant_id`: String (The ID returned from Step 1).
  - `twilio_number`: String (Must be exact E.164 format, e.g., +447000000000)
  - `manager_number`: String (For human escalations)
- **What it does:** Securely passes your master Twilio credentials to Vapi so Vapi can take control of the phone line and map it to the correct AI Agent.
- **Returns:** JSON success confirmation.

---

## 📞 How to Handle Post-Call Data (Orders & Transcripts)

Because we use Vapi, **this microservice does NOT store data.** Vapi handles it natively.

1. **Setup a Webhook on your Main Backend:** Create an endpoint on your SaaS like `POST https://your-main-backend.com/vapi-webhook`.
2. **Configure Vapi:** In your Vapi Dashboard, set that URL as your Server URL.
3. **Receive the Data:** The moment a customer hangs up, Vapi will send a massive JSON payload (`end-of-call-report`) to your webhook.
4. **Identify the Business:** Inside the `metadata` object of that payload, you will see the `business_id` that you passed to us in Step 1. Use this to save the `transcript`, `summary`, and structured `order_items` into the correct business's database row!

## 🎙️ Frontend Note (Test Voice Window)
Your React Frontend does NOT need to talk to this Python microservice to test the voice. 
Simply use the `@vapi-ai/web` SDK, provide your `VAPI_PUBLIC_KEY`, and pass in the `assistant_id`. The browser will connect directly to Vapi.
