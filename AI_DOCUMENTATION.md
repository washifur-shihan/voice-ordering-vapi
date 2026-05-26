# Voice Agent AI Module - Backend Handoff Documentation

This document provides a deep technical dive into the AI mechanism inside this codebase. It is written specifically for the backend developer inheriting this project to integrate it with databases and a SaaS multi-tenant infrastructure.

## Core Design Philosophy
The AI engine does **not** rely on rigid conversational trees (e.g., "Press 1 for Sales, Press 2 for Support"). Instead, it utilizes **Conversational RAG (Retrieval-Augmented Generation)** coupled with **Dynamic Intent Classification** to act as a human-like operator.

## How the AI "Thinks"

The main brain of the system is located in `app/rag_answer.py`. Every time a user speaks, Twilio transcribes the speech and pings the `/voice-process` endpoint, which invokes `generate_answer()`.

Here is the exact step-by-step logic the AI performs on every sentence:

### 1. Conversational Memory Injection
```python
transcript = get_transcript(call_id)
```
Before the AI tries to answer, it fetches the *entire* conversation history of that specific phone call. If the user previously said "I want a blue shirt", and the AI asked "What size?", and the user replies "Large", the AI needs to know *what* is large. By injecting the `transcript` into standard queries, the AI maintains perfect continuity.

### 2. Micro-LLM State Routing (Intent Classification)
Before answering the question, the system needs to know which "State" the caller is in.
It queries OpenAI with a fast, cheap model prompt consisting of the transcript and the latest user sentence, instructing it to return exactly one of 5 strict strings:
* `"order_add"`
* `"order_confirm"`
* `"order_cancel"`
* `"escalation"`
* `"faq"`

**Why This Matters to Backend Devs:**
By keeping Intent Detection purely dynamic via LLMs, the system never relies on flakey string matching (e.g., `if "cancel" in text:`). You can safely hook the `"order_cancel"` output up to your backend Order Database and trust that it triggers smoothly, even if the user says something weird like *"You know what? Let's forget the pizza for now."* 

### 3. State-Based Execution
Based on the intent, the code bifurcates:

#### A. The Order Pipeline (`intent in ["order_add", "order_confirm", "order_cancel"]`)
If the user is ordering, the code manages an in-memory dictionary `state["order_draft"]`. 
If `"order_add"`, it injects the transcript into another strict LLM prompt forcing OpenAI to extract a flat JSON list of items and quantities from the latest sentence. 
- **BE Task:** When the intent hits `"order_confirm"`, the AI structures the final `order_data` dictionary and ends the order flow. **You need to take this `order_data` dictionary and POST it to your Stripe/POS/Database.**

#### B. The Escalation Pipeline (`intent == "escalation"`)
If the user asks for a human, the code instantly aborts AI generation and tells Twilio to transfer the call via TwiML `<Dial>`.
- **BE Task:** Right now, the dial number is hardcoded to `+1234567890`. You must dynamically inject the actual Phone Number of the business owner querying your database.

#### C. The FAQ Pipeline (`intent == "faq"`)
If the user isn't ordering or escalating, they are asking a question.
1. `find_relevant_chunk()` searches the local knowledge base (`current_report.txt`) for the most relevant data.
2. It concatenates the **Persona Script**, the **Business Knowledge**, the **Live Transcript**, and the **Newest Question**.
3. It asks OpenAI to answer the user securely *based only on* the provided knowledge to heavily prevent hallucinations.
4. The backend then speaks the answer over Twilio.

## Memory Optimization Warning (Crucial API Impact)
Because the `transcript` grows with every conversational turn, the Token Count sent to OpenAI will increase identically. 
For 5-minute calls, this is highly efficient and fine. 
If your SaaS allows 60-minute calls, you will need to implement a **Rolling Window Transcript** (e.g., `"\n".join(transcript[-10:])`) inside `get_transcript()` so that context windows do not exceed model limits or cause high OpenAI billing latency.

## Multi-Tenancy Strategy (The Main Handoff Task)

Right now, the AI loads the business identity manually across all calls:
```python
with open("reports/current_report.txt", "r", encoding="utf-8") as f:
    report_text = f.read()
```
For the SaaS product to function fully:
1. Replace `report_path` and `script_path` parameters. 
2. When the `/voice` webhook hits your FastApi server, read the `To` phone number. 
3. Query `SELECT business_id, aws_knowledge_url, aws_script_url FROM PhoneNumbers WHERE twilio_number = {To_number}`.
4. Pass those dynamically loaded documents into the exact same AI pipeline.

Do this, connect a database to replace `.txt` logs, and the platform will be production-ready!
