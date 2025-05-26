import os
import smtplib
from typing import AsyncGenerator, Dict
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from openai import OpenAI
from pypdf import PdfReader
from agents import Agent, Runner, function_tool,InputGuardrail, GuardrailFunctionOutput, handoff, trace
from agents.model_settings import ModelSettings
from pydantic import BaseModel
from dotenv import load_dotenv
import asyncio
import os
from typing import Dict
import gradio as gr
import time
from collections import defaultdict
import threading
from datetime import datetime, timedelta
load_dotenv(override=True)
# Rate limiter configuration
RATE_LIMIT_REQUESTS = 2
RATE_LIMIT_WINDOW = 60  # 1 minute in seconds
# Email-specific rate limiter configuration
EMAIL_RATE_LIMIT_REQUESTS = 1  # Allow 5 emails per hour
EMAIL_RATE_LIMIT_WINDOW = 60  # 1 hour in seconds
# Rate limiter storage
rate_limiter_data = {
    "requests": defaultdict(list),
    "lock": threading.Lock()
}

def is_rate_limited() -> tuple[bool, str]:
    """Check if the current request should be rate limited"""
    current_time = datetime.now()
    
    with rate_limiter_data["lock"]:
        # Use a simple key for global rate limiting, or you could use IP/user ID
        key = "global"  # You can change this to user-specific if needed
        
        # Clean old requests (older than 1 minute)
        rate_limiter_data["requests"][key] = [
            req_time for req_time in rate_limiter_data["requests"][key]
            if current_time - req_time < timedelta(seconds=RATE_LIMIT_WINDOW)
        ]
        
        # Check if rate limit exceeded
        if len(rate_limiter_data["requests"][key]) >= RATE_LIMIT_REQUESTS:
            oldest_request = min(rate_limiter_data["requests"][key])
            reset_time = oldest_request + timedelta(seconds=RATE_LIMIT_WINDOW)
            wait_seconds = int((reset_time - current_time).total_seconds())
            
            return True, f"Rate limit exceeded. Please try again after {wait_seconds} seconds."
        
        # Add current request to the list
        rate_limiter_data["requests"][key].append(current_time)
        
        return False, ""


# Email rate limiter storage
email_rate_limiter_data = {
    "requests": defaultdict(list),
    "lock": threading.Lock()
}

def is_email_rate_limited() -> tuple[bool, str]:
    """Check if the current email request should be rate limited"""
    current_time = datetime.now()
    
    with email_rate_limiter_data["lock"]:
        # Use a simple key for global email rate limiting
        key = "email_global"  # You can change this to user-specific if needed
        
        # Clean old requests (older than the window)
        email_rate_limiter_data["requests"][key] = [
            req_time for req_time in email_rate_limiter_data["requests"][key]
            if current_time - req_time < timedelta(seconds=EMAIL_RATE_LIMIT_WINDOW)
        ]
        
        # Check if rate limit exceeded
        if len(email_rate_limiter_data["requests"][key]) >= EMAIL_RATE_LIMIT_REQUESTS:
            oldest_request = min(email_rate_limiter_data["requests"][key])
            reset_time = oldest_request + timedelta(seconds=EMAIL_RATE_LIMIT_WINDOW)
            wait_minutes = int((reset_time - current_time).total_seconds() / 60)
            wait_seconds = int((reset_time - current_time).total_seconds() % 60)
            
            if wait_minutes > 0:
                return True, f"Email rate limit exceeded. Please try again after {wait_minutes} minutes and {wait_seconds} seconds."
            else:
                return True, f"Email rate limit exceeded. Please try again after {wait_seconds} seconds."
        
        # Add current request to the list
        email_rate_limiter_data["requests"][key].append(current_time)
        
        return False, ""


@function_tool
def send_email(receiver_email: str, subject: str, html_body: str) -> Dict[str, str]:
    print(f"[DEBUG] receiver_email: {receiver_email}")
    print(f"[DEBUG] subject: {subject}")
    print(f"[DEBUG] html_body: {html_body}")

    is_limited, error_message = is_email_rate_limited()
    if is_limited:
        print(f"[EMAIL RATE LIMIT] {error_message}")
        return {"status": "failed", "error": error_message}
    """Send an email using Gmail SMTP with the given receiver, subject, and HTML body."""
    
    sender_email = os.environ.get("GMAIL_SENDER_EMAIL")     # Your Gmail address
    app_password = os.environ.get("GMAIL_APP_PASSWORD")      # Gmail App Password

    try:
        # Create the email
        message = MIMEMultipart()
        message["From"] = sender_email
        message["To"] = receiver_email
        message["Subject"] = subject
        message.attach(MIMEText(html_body, "html"))

        # Send the email via Gmail SMTP server
        with smtplib.SMTP_SSL("smtp.gmail.com", 465 ) as server:
            server.login(sender_email, app_password)
            server.sendmail(sender_email, receiver_email, message.as_string())

        # print(f"✅ Email sent successfully to {receiver_email}.")
        return {"status": "success", "to": receiver_email}

    except Exception as e:
        print(f"❌ Error sending email to {receiver_email}: {e}")
        return {"status": "failed", "error": str(e)}

class Me:

    def __init__(self):
        self.openai = OpenAI()
        self.name = "Aayush Kumar"
        self.email= os.environ.get("GMAIL_SENDER_EMAIL")
        self.phone=9304154450
        reader = PdfReader("me/Profile.pdf")
        self.linkedin = ""
        for page in reader.pages:
            text = page.extract_text()
            if text:
                self.linkedin += text
        reader = PdfReader("me/aayush_kumar-fullStack.pdf")
        self.resume = ""
        for page in reader.pages:
            text = page.extract_text()
            if text:
                self.resume += text
        with open("me/summary.txt", "r", encoding="utf-8") as f:
            self.summary = f.read()
        

        self.conversational_instruction = f"""
You are {self.name}'s virtual assistant and professional representative. You are helping visitors to {self.name}'s website learn about their background, skills, and experience.

GREETING & INTRODUCTION:
Start conversations with: "Hello! I'm {self.name}'s virtual assistant. I can tell you about my professional background, skills, and projects. Feel free to ask anything! Would you like to know about my work experience, education, or something specific?"

YOUR ROLE:
- Represent {self.name} professionally and engagingly
- Answer questions about career, background, skills, and experience
- Facilitate email connections when requested
- Be conversational but maintain professionalism

AVAILABLE INFORMATION:
## Summary:
{self.summary}

## LinkedIn Profile:
{self.linkedin}

## Resume:
{self.resume}

CONTACT INFORMATION:
- Email: {self.email}
- Phone: {self.phone}

GUIDELINES:
- Stay in character as {self.name}
- Be professional and engaging (like talking to potential clients/employers)
- If you don't know something, encourage them to get in touch via email
- Provide concise but informative responses
- Show enthusiasm about {self.name}'s work and experience

Remember: You ARE {self.name} speaking in first person about your own experience.
"""
    
        self.email_instructions = """
You are an intelligent email-sending assistant.

Your task is to:
1. Extract the **recipient email address** from the user input. Look for patterns like `email:`, `my email is`, `send it to`, or `@domain.com`. If no valid email is found, respond with: **"Recipient email is required to send the email."**
2. Extract the **subject** of the email. If the subject is not explicitly provided, generate one based on the message content. If that’s not possible, use the default: **"Greetings from our team."**
3. Extract the **email body/message**. If none is found, use the default: **"Hello, hope you're having a great day!"**

Important:
- Never reuse previously seen email addresses or cached values.
- Always extract fresh values based on the **current user input** only.
- You are calling a tool to send this email. Ensure the tool receives three arguments: `receiver_email`, `subject`, and `html_body`.

Examples:
- Input: "Send a thank-you email to john@example.com" → receiver_email: john@example.com, subject: Thank You, html_body: Thank you!
- Input: "Can you send me an email? Here is my email: kumar.aayush245@gmail.com" → receiver_email: kumar.aayush245@gmail.com, subject: Greetings from our team, html_body: Hello, hope you're having a great day!
"""

       
        self.standalone_instruction = "You are a grammar correction assistant. Your task is to convert any input query into a grammatically correct, standalone question or sentence. Additionally, highlight any contact details or email addresses present in the input."


me= Me()
class EmailInputType(BaseModel):
    receiver_email: str
    subject: str
    html_body: str

email_agent = Agent(
    name="Email Agent",
    handoff_description="Handled email-related conversations",
    instructions= me.email_instructions,
    tools=[send_email],
    model="gpt-4o-mini",
)
standalone_agent = Agent(
    name="Standalone Agent",
    instructions= me.standalone_instruction,
    model="gpt-4o-mini",
)
async def standalone_guardrail(ctx, agent, input_data):
    with trace("standalone_guardrail"):
        result = await Runner.run(standalone_agent, input_data, context=ctx.context)
        print(f"standalone_guardrail -{result.final_output}")
        return GuardrailFunctionOutput(output_info = result.final_output, tripwire_triggered=not result.final_output)

def onEmailHandOff(ctx, input):
    print(f"data {input}")


conversational_agent = Agent(
    name="Conversational Agent",
    instructions= me.conversational_instruction,
    handoffs=[handoff(agent=email_agent, input_type=EmailInputType, on_handoff=onEmailHandOff)],
    model="gpt-4o-mini",
    input_guardrails=[
        InputGuardrail(guardrail_function=standalone_guardrail),
    ],
)

async def chat_with_agent_stream(message: str, history: list) -> AsyncGenerator[str, None]:
    """Stream the agent's response with proper sentence building"""
    try:
        is_limited, error_message = is_rate_limited()
        if is_limited:
            print(f"[RATE LIMIT] {error_message}")
            yield f"{error_message}"
            return
        # First get the complete response (we'll simulate streaming)
        with trace("conversational_agent"):
            result = await Runner.run(conversational_agent, message)
            full_response = result.final_output
        
        # Build up the response gradually
            current_display = ""
            for word in full_response.split():
                current_display += word + " "
                yield current_display  # Yield the complete response so far
                await asyncio.sleep(0.10)  # Adjust speed as needed
        
        # Ensure we yield the complete final response
            if current_display.strip() != full_response.strip():
                yield full_response
            
    except Exception as e:
        yield f"Error: {str(e)}"

# demo = gr.ChatInterface(
#     fn=chat_with_agent_stream,
#     title=f"{me.name}'s Virtual AI Assistant",
#     description=f"Ask me anything about {me.name}'s professional background and experience.",
#     examples=[
#         "Tell me about your work experience",
#         "What skills do you have?",
#         "What projects have you worked on?"
#     ],
#     # theme="soft"
# )

demo = gr.ChatInterface(
    fn=chat_with_agent_stream,
    title=f"{me.name}'s Virtual AI Assistant",
    description=f"Ask me anything about {me.name}'s professional background and experience.",
    examples=[
        "Tell me about your work experience",
        "What skills do you have?",
        "What projects have you worked on?",
        "Send a connecting email to receiver@gmail.com?"
    ],
    # Control chat display parameters
    chatbot=gr.Chatbot(
        height=500,  # Increase height of chat box
        show_label=False,
        container=True,
        scale=1,
        bubble_full_width=False,
    ),
    textbox=gr.Textbox(
        placeholder="Ask me anything about my professional background...",
        container=False,
        scale=7,
        # Set font size for input (though this is limited)
        show_label=False,
    ),
    theme="soft"  # You can still use themes
)



if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7864))
    demo.launch(server_name="0.0.0.0", server_port=port)


