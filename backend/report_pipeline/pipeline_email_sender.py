import os
import logging
import time
from typing import List, Dict

logger = logging.getLogger(__name__)

def send_email(subject: str, html_body: str, excel_path: str, to_addresses: List[str], cc_addresses: List[str]) -> Dict[str, any]:
    if os.getenv("MOCK_OUTLOOK", "false").lower() == "true":
        try:
            with open("./debug_email_output.html", "w", encoding="utf-8") as f:
                f.write(html_body)
            logger.info(f"MOCK MODE: Email would have been sent to {to_addresses}. Saved to debug_email_output.html")
            return {"success": True, "mock": True, "error": None}
        except Exception as e:
            return {"success": False, "mock": True, "error": str(e)}

    try:
        import win32com.client
        from win32com.client import pythoncom
    except ImportError:
        logger.error("win32com.client is not installed or not supported on this OS.")
        return {"success": False, "error": "win32com not available"}

    def _attempt_send():
        pythoncom.CoInitialize()
        try:
            outlook = win32com.client.Dispatch("Outlook.Application")
            mail = outlook.CreateItem(0)
            mail.To = ";".join(to_addresses)
            if cc_addresses:
                mail.CC = ";".join(cc_addresses)
            mail.Subject = subject
            mail.HTMLBody = html_body
            if excel_path and os.path.exists(excel_path):
                mail.Attachments.Add(os.path.abspath(excel_path))
            mail.Send()
            return True, None
        except Exception as e:
            return False, str(e)
        finally:
            pythoncom.CoUninitialize()

    success, err = _attempt_send()
    if not success:
        logger.warning(f"First email send attempt failed: {err}. Retrying in 2 seconds...")
        time.sleep(2)
        success, err = _attempt_send()
        
    if success:
        return {"success": True, "error": None}
    else:
        logger.error(f"[pipeline_email_sender] Failed to send email via Outlook after retry: {err}")
        return {"success": False, "error": err}