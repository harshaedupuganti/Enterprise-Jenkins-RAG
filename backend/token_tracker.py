import csv
import os
from datetime import datetime

def log_token_usage(cb, user_query: str, log_file: str = "token_usage_log.csv"):
    """
    Silently logs OpenAI token usage and cost to a CSV file.
    Takes the LangChain callback object (cb) and the user's text query.
    """
    file_exists = os.path.isfile(log_file)
    
    try:
        with open(log_file, mode='a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            # Write headers if the file is brand new
            if not file_exists:
                writer.writerow([
                    "Timestamp", 
                    "Prompt Tokens", 
                    "Completion Tokens", 
                    "Total Tokens", 
                    "Cost (USD)", 
                    "User Query"
                ])
            
            # Write the tracked data for this request
            writer.writerow([
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                cb.prompt_tokens,
                cb.completion_tokens,
                cb.total_tokens,
                round(cb.total_cost, 6),
                user_query
            ])
            
    except Exception as e:
        # If the file is locked or fails, print a warning but DON'T crash the chat
        print(f"Warning: Failed to write to token tracker log: {e}")