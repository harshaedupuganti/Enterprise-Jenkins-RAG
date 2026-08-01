import requests
import logging

# Set up enterprise logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

JENKINS_API_URL = "http://skobde-brk-cbt1.ad.trw.com:8080/computer/api/json"

def fetch_jenkins_nodes() -> list[dict]:
    """Fetches dynamic node data from the Jenkins API."""
    try:
        logger.info(f"Fetching live data from {JENKINS_API_URL}")
        # The timeout ensures the server doesn't hang if Jenkins is down
        response = requests.get(JENKINS_API_URL, timeout=10)
        response.raise_for_status() 
        data = response.json()
        
        # Extracting the list of computers
        return data.get("computer", [])
    except Exception as e:
        logger.error(f"Failed to fetch Jenkins data: {e}")
        return []